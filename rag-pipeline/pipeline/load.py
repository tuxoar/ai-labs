"""Postgres write path (role: rag_ingest). Idempotent by content hash:
re-running an ingest skips existing chunks; adding a second embedder fills
the empty column on existing rows instead of duplicating them."""

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
        for i, ch in enumerate(chunks):
            row = conn.execute(
                """
                INSERT INTO rag.chunks
                    (collection_name, book_id, chapter, seq, text, content_hash, meta)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (collection_name, content_hash) DO NOTHING
                RETURNING id
                """,
                (collection, book_id, ch.chapter, ch.seq, ch.text, ch.content_hash, json.dumps(ch.meta)),
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
                   count(DISTINCT book_id)               AS books
            FROM rag.chunks GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
