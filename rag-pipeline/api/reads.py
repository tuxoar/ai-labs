"""Read endpoints' SQL: passage / section / chapter / catalog. Every read is
capped by max_context_chars and says when it truncated — the agent must ask
for more deliberately rather than receive an uncontrolled dump."""

from __future__ import annotations

from typing import Any

import psycopg


def _cap(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def get_passage(conn: psycopg.Connection, passage_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT c.id::text AS passage_id, c.section_id::text AS section_id, c.chapter_id::text AS chapter_id,
               c.book_id::text AS book_id, b.title AS book, b.author, c.chapter, s.heading AS section,
               c.seq, c.collection_name AS collection, c.text, c.meta
        FROM rag.chunks c
        JOIN rag.books b ON b.id = c.book_id
        LEFT JOIN rag.sections s ON s.id = c.section_id
        WHERE c.id = %s::uuid
        """,
        (passage_id,),
    ).fetchone()
    if not row:
        return None
    # Neighbours: previous/next passage in the same collection + book.
    nb = conn.execute(
        """
        SELECT id::text AS passage_id, seq, section_id::text AS section_id
        FROM rag.chunks
        WHERE collection_name = %s AND book_id = %s::uuid AND seq IN (%s, %s)
        ORDER BY seq
        """,
        (row["collection"], row["book_id"], row["seq"] - 1, row["seq"] + 1),
    ).fetchall()
    row["neighbours"] = {"prev": None, "next": None}
    for n in nb:
        key = "prev" if n["seq"] < row["seq"] else "next"
        row["neighbours"][key] = n
    return row


def get_section(conn: psycopg.Connection, section_id: str, max_chars: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT s.id::text AS section_id, s.chapter_id::text AS chapter_id, ch.book_id::text AS book_id,
               b.title AS book, b.author, ch.title AS chapter, s.heading, s.depth, s.seq,
               s.text_md, length(s.text_md) AS chars
        FROM rag.sections s
        JOIN rag.chapters ch ON ch.id = s.chapter_id
        JOIN rag.books b ON b.id = ch.book_id
        WHERE s.id = %s::uuid
        """,
        (section_id,),
    ).fetchone()
    if not row:
        return None
    text, truncated = _cap(row.pop("text_md"), max_chars)
    row["text"] = text
    row["truncated"] = truncated
    row["passages"] = [
        r["passage_id"]
        for r in conn.execute(
            "SELECT id::text AS passage_id FROM rag.chunks WHERE section_id = %s::uuid ORDER BY collection_name, seq",
            (section_id,),
        ).fetchall()
    ]
    return row


def get_chapter(conn: psycopg.Connection, chapter_id: str, max_chars: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT ch.id::text AS chapter_id, ch.book_id::text AS book_id, b.title AS book, b.author,
               ch.title AS chapter, ch.seq, ch.text_md, length(ch.text_md) AS chars
        FROM rag.chapters ch
        JOIN rag.books b ON b.id = ch.book_id
        WHERE ch.id = %s::uuid
        """,
        (chapter_id,),
    ).fetchone()
    if not row:
        return None
    text_md = row.pop("text_md")
    sections = conn.execute(
        """
        SELECT id::text AS section_id, seq, heading, depth, length(text_md) AS chars
        FROM rag.sections WHERE chapter_id = %s::uuid ORDER BY seq
        """,
        (chapter_id,),
    ).fetchall()
    row["sections"] = sections
    if len(text_md) <= max_chars:
        row["text"] = text_md
        row["truncated"] = False
    else:
        # Over budget: hand back the section map instead of a cut-off dump so
        # the caller can pick the sections it actually needs.
        row["text"] = None
        row["truncated"] = True
    return row


def search_books(
    conn: psycopg.Connection,
    author: str | None,
    title: str | None,
    topic: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    where = []
    if author:
        params["author"] = f"%{author}%"
        where.append("b.author ILIKE %(author)s")
    if title:
        params["title"] = f"%{title}%"
        where.append("b.title ILIKE %(title)s")
    if topic:
        params["topic"] = topic
        where.append(
            """EXISTS (
                SELECT 1 FROM rag.chapters ch
                LEFT JOIN rag.sections s ON s.chapter_id = ch.id
                WHERE ch.book_id = b.id
                  AND (to_tsvector('english', ch.title) @@ websearch_to_tsquery('english', %(topic)s)
                       OR to_tsvector('english', coalesce(s.heading, '')) @@ websearch_to_tsquery('english', %(topic)s))
            )"""
        )
    sql = f"""
        SELECT b.id::text AS book_id, b.title, b.author, b.ingested_at,
               (SELECT count(*) FROM rag.chapters ch WHERE ch.book_id = b.id) AS chapters,
               (SELECT array_agg(DISTINCT collection_name ORDER BY collection_name)
                  FROM rag.chunks c WHERE c.book_id = b.id) AS collections
        FROM rag.books b
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY b.title
        LIMIT %(limit)s
    """
    return conn.execute(sql, params).fetchall()


def list_collections(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT collection_name AS collection, count(*) AS chunks, count(DISTINCT book_id) AS books,
               count(emb_nomic) AS nomic, count(emb_bgem3) AS bgem3, count(section_id) AS with_section
        FROM rag.chunks GROUP BY 1 ORDER BY 1
        """
    ).fetchall()


def expand_parents(
    conn: psycopg.Connection,
    results: list[dict[str, Any]],
    level: str,
    max_items: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Parent expansion for the strongest hits: unique section/chapter ids in
    rank order, text fetched under ONE shared character budget."""
    key = "section_id" if level == "section" else "chapter_id"
    seen: list[str] = []
    origins: dict[str, list[str]] = {}
    for r in results:
        pid = r.get(key)
        if not pid:
            continue
        if pid not in origins:
            if len(seen) >= max_items:
                continue
            seen.append(pid)
            origins[pid] = []
        origins[pid].append(r["passage_id"])
    out: list[dict[str, Any]] = []
    budget = max_chars
    for pid in seen:
        if level == "section":
            parent = get_section(conn, pid, budget)
            heading = parent["heading"] if parent else None
        else:
            parent = get_chapter(conn, pid, budget)
            heading = parent["chapter"] if parent else None
        if not parent:
            continue
        text = parent.get("text") or ""
        budget -= len(text)
        out.append(
            {
                "level": level,
                "id": pid,
                "heading": heading,
                "book": parent["book"],
                "chapter": parent["chapter"],
                "chars": parent["chars"],
                "truncated": parent["truncated"],
                "text": text,
                "from_passage_ids": origins[pid],
            }
        )
        if budget <= 0:
            break
    return out
