"""Postgres write path (role: rag_ingest). Idempotent by content hash:
re-running an ingest skips existing chunks; adding a second embedder fills
the empty column on existing rows instead of duplicating them. The document
hierarchy (chapters, sections) is upserted per book and is independent of
collections — every variant shares the same parents."""

import json

import psycopg

from .chunk import Chunk
from .config import EMBEDDERS, Settings
from .parse import Book


def existing_hashes(settings: Settings, collection: str, column: str) -> set[str]:
    """Hashes already ingested AND embedded (for the given model column) —
    the caller skips these before spending gateway budget on embeddings."""
    with psycopg.connect(settings.pg_dsn) as conn:
        rows = conn.execute(
            f"SELECT content_hash FROM rag.chunks WHERE collection_name = %s AND {column} IS NOT NULL",
            (collection,),
        ).fetchall()
    return {r[0] for r in rows}


def upsert_book(conn: psycopg.Connection, book: Book) -> str:
    row = conn.execute(
        """
        INSERT INTO rag.books (title, author, source_hash)
        VALUES (%s, %s, %s)
        ON CONFLICT (source_hash) DO UPDATE SET title = EXCLUDED.title
        RETURNING id
        """,
        (book.title, book.author, book.source_hash),
    ).fetchone()
    return str(row[0])


class Structure:
    """Parent ids for one book: chapter_seq -> chapter_id,
    (chapter_seq, section_seq) -> section_id."""

    def __init__(self) -> None:
        self.chapters: dict[int, str] = {}
        self.sections: dict[tuple[int, int], str] = {}


def upsert_structure(conn: psycopg.Connection, book: Book, book_id: str) -> Structure:
    """Idempotent: a chapter whose markdown hash is unchanged keeps its row and
    sections; a changed chapter (new parser, new EPUB edition) is updated and
    its sections rebuilt (chunks.section_id -> NULL via FK, re-pointed by the
    caller's inserts/backfill)."""
    st = Structure()
    for ch in book.chapters:
        row = conn.execute(
            "SELECT id, content_hash FROM rag.chapters WHERE book_id = %s AND seq = %s",
            (book_id, ch.seq),
        ).fetchone()
        if row and row[1] == ch.content_hash:
            chapter_id = str(row[0])
            existing = conn.execute(
                "SELECT seq, id FROM rag.sections WHERE chapter_id = %s", (chapter_id,)
            ).fetchall()
            if len(existing) == len(ch.sections):
                st.chapters[ch.seq] = chapter_id
                for seq, sid in existing:
                    st.sections[(ch.seq, seq)] = str(sid)
                continue
        if row:
            chapter_id = str(row[0])
            conn.execute(
                "UPDATE rag.chapters SET title = %s, text_md = %s, content_hash = %s WHERE id = %s",
                (ch.title, ch.markdown, ch.content_hash, chapter_id),
            )
            conn.execute("DELETE FROM rag.sections WHERE chapter_id = %s", (chapter_id,))
        else:
            chapter_id = str(
                conn.execute(
                    """
                    INSERT INTO rag.chapters (book_id, seq, title, text_md, content_hash)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """,
                    (book_id, ch.seq, ch.title, ch.markdown, ch.content_hash),
                ).fetchone()[0]
            )
        st.chapters[ch.seq] = chapter_id
        for sec in ch.sections:
            sid = conn.execute(
                """
                INSERT INTO rag.sections (chapter_id, seq, heading, depth, text_md, content_hash)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (chapter_id, sec.seq, sec.heading, sec.depth, sec.markdown, sec.content_hash),
            ).fetchone()[0]
            st.sections[(ch.seq, sec.seq)] = str(sid)
    return st


def backfill_parents(conn: psycopg.Connection, book_id: str) -> int:
    """Point pre-005 chunks (any collection) at their chapter row using the
    chapter_seq every chunk has carried in meta since Phase 1."""
    cur = conn.execute(
        """
        UPDATE rag.chunks c
           SET chapter_id = ch.id
          FROM rag.chapters ch
         WHERE c.book_id = %s AND c.chapter_id IS NULL
           AND ch.book_id = c.book_id
           AND ch.seq = (c.meta->>'chapter_seq')::int
        """,
        (book_id,),
    )
    return cur.rowcount


def ensure_structure(settings: Settings, book: Book) -> dict:
    """Book + chapters + sections upserted, old chunks backfilled. Safe to run
    before any embedding is spent and on every re-run."""
    with psycopg.connect(settings.pg_dsn) as conn:
        book_id = upsert_book(conn, book)
        st = upsert_structure(conn, book, book_id)
        backfilled = backfill_parents(conn, book_id)
        conn.commit()
    return {"book_id": book_id, "chapters": len(st.chapters), "sections": len(st.sections), "backfilled": backfilled}


def load_chunks(
    settings: Settings,
    book: Book,
    collection: str,
    chunks: list[Chunk],
    embeddings_by_model: dict[str, list[list[float]]],
) -> dict:
    """Insert chunks (skip existing by hash), then set embedding columns.
    embeddings_by_model maps gateway model alias -> vectors aligned with chunks."""
    stats = {"inserted": 0, "skipped": 0, "embedded": {m: 0 for m in embeddings_by_model}}
    with psycopg.connect(settings.pg_dsn) as conn:
        book_id = upsert_book(conn, book)
        st = upsert_structure(conn, book, book_id)
        for i, ch in enumerate(chunks):
            chapter_id = st.chapters.get(ch.chapter_seq)
            section_id = st.sections.get((ch.chapter_seq, ch.section_seq)) if ch.section_seq else None
            row = conn.execute(
                """
                INSERT INTO rag.chunks
                    (collection_name, book_id, chapter, seq, text, content_hash, meta, chapter_id, section_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (collection_name, content_hash) DO NOTHING
                RETURNING id
                """,
                (collection, book_id, ch.chapter, ch.seq, ch.text, ch.content_hash, json.dumps(ch.meta),
                 chapter_id, section_id),
            ).fetchone()
            stats["inserted" if row else "skipped"] += 1

            for model, vectors in embeddings_by_model.items():
                column, dims = EMBEDDERS[model]
                vec = vectors[i]
                if len(vec) != dims:
                    raise ValueError(f"{model}: expected {dims} dims, got {len(vec)}")
                cur = conn.execute(
                    # psycopg composes identifiers unsafely via f-string ONLY for
                    # the column, which comes from the EMBEDDERS allow-list.
                    f"""
                    UPDATE rag.chunks SET {column} = %s::vector
                    WHERE collection_name = %s AND content_hash = %s AND {column} IS NULL
                    """,
                    (json.dumps(vec), collection, ch.content_hash),
                )
                stats["embedded"][model] += cur.rowcount
        backfill_parents(conn, book_id)
        conn.commit()
    return stats


def collection_stats(settings: Settings) -> list[tuple]:
    with psycopg.connect(settings.pg_dsn) as conn:
        return conn.execute(
            """
            SELECT collection_name,
                   count(*)                              AS chunks,
                   count(emb_nomic)                      AS nomic,
                   count(emb_bgem3)                      AS bgem3,
                   count(DISTINCT book_id)               AS books,
                   count(section_id)                     AS with_section
            FROM rag.chunks GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
