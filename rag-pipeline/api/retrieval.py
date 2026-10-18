"""Retrieval SQL: lexical (tsvector / ts_rank_cd), dense (pgvector HNSW with a
per-query ef_search), and hybrid = both legs fused with Reciprocal Rank
Fusion in ONE statement. Pure functions build the SQL + params so they are
unit-testable without a database; `run_search` executes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from .config import EMBEDDERS

MODES = ("lexical", "dense", "hybrid")

# Provenance columns every result carries (see PLAN.md tool contract).
_SELECT_PROVENANCE = """
    c.id::text              AS passage_id,
    c.section_id::text      AS section_id,
    c.chapter_id::text      AS chapter_id,
    c.book_id::text         AS book_id,
    b.title                 AS book,
    b.author                AS author,
    c.chapter               AS chapter,
    s.heading               AS section,
    c.seq                   AS seq,
    c.collection_name       AS collection,
    c.text                  AS text
"""

_JOIN_PROVENANCE = """
    JOIN rag.books b      ON b.id = c.book_id
    LEFT JOIN rag.sections s ON s.id = c.section_id
"""


@dataclass(frozen=True)
class SearchSpec:
    query: str
    collection: str
    mode: str = "hybrid"
    embedder: str = "embed-nomic"
    top_k: int = 10
    candidates: int = 50
    ef_search: int = 100
    rrf_k: int = 60
    book_id: str | None = None
    author: str | None = None


def _filters(spec: SearchSpec, params: dict[str, Any]) -> str:
    """Optional filters applied INSIDE each leg so authorization/scoping
    happens before ranking, never after."""
    sql = ""
    if spec.book_id:
        params["book_id"] = spec.book_id
        sql += " AND c.book_id = %(book_id)s::uuid"
    if spec.author:
        params["author"] = f"%{spec.author}%"
        sql += " AND EXISTS (SELECT 1 FROM rag.books fb WHERE fb.id = c.book_id AND fb.author ILIKE %(author)s)"
    return sql


def build_search_sql(spec: SearchSpec, query_vector: list[float] | None) -> tuple[str, dict[str, Any]]:
    """Returns (sql, params). query_vector is required for dense/hybrid."""
    if spec.mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if spec.embedder not in EMBEDDERS:
        raise ValueError(f"unknown embedder {spec.embedder}")
    column, dims = EMBEDDERS[spec.embedder]
    params: dict[str, Any] = {
        "collection": spec.collection,
        "candidates": spec.candidates,
        "top_k": spec.top_k,
        "rrf_k": spec.rrf_k,
        "qtext": spec.query,
    }
    where_filters = _filters(spec, params)
    legs: list[str] = []

    if spec.mode in ("dense", "hybrid"):
        if query_vector is None or len(query_vector) != dims:
            raise ValueError(f"{spec.embedder}: query vector of {dims} dims required")
        params["qvec"] = json.dumps(query_vector)
        # Inner ORDER BY <=> LIMIT is the shape pgvector's HNSW planner wants;
        # rank is assigned outside so the index scan is not defeated.
        legs.append(f"""
dense AS (
    SELECT id, row_number() OVER (ORDER BY dist) AS rnk, 1 - dist AS score
    FROM (
        SELECT c.id, c.{column} <=> %(qvec)s::vector AS dist
        FROM rag.chunks c
        WHERE c.collection_name = %(collection)s AND c.{column} IS NOT NULL{where_filters}
        ORDER BY dist
        LIMIT %(candidates)s
    ) d
)""")
    if spec.mode in ("lexical", "hybrid"):
        legs.append(f"""
lexical AS (
    SELECT id, row_number() OVER (ORDER BY score DESC) AS rnk, score
    FROM (
        SELECT c.id, ts_rank_cd(c.tsv, q) AS score
        FROM rag.chunks c, websearch_to_tsquery('english', %(qtext)s) q
        WHERE c.collection_name = %(collection)s AND c.tsv @@ q{where_filters}
        ORDER BY score DESC
        LIMIT %(candidates)s
    ) l
)""")

    if spec.mode == "hybrid":
        fused = """
fused AS (
    SELECT coalesce(d.id, l.id) AS id,
           d.score AS dense_score, l.score AS lexical_score,
           coalesce(1.0 / (%(rrf_k)s + d.rnk), 0) + coalesce(1.0 / (%(rrf_k)s + l.rnk), 0) AS rrf
    FROM dense d FULL OUTER JOIN lexical l ON d.id = l.id
)"""
        order = "f.rrf DESC, f.dense_score DESC NULLS LAST"
    elif spec.mode == "dense":
        fused = """
fused AS (SELECT id, score AS dense_score, NULL::real AS lexical_score, 1.0 / (%(rrf_k)s + rnk) AS rrf FROM dense)"""
        order = "f.dense_score DESC"
    else:
        fused = """
fused AS (SELECT id, NULL::float AS dense_score, score AS lexical_score, 1.0 / (%(rrf_k)s + rnk) AS rrf FROM lexical)"""
        order = "f.lexical_score DESC"

    sql = f"""
WITH {",".join(legs)},{fused}
SELECT {_SELECT_PROVENANCE},
       f.lexical_score::float AS lexical_score,
       f.dense_score::float   AS dense_score,
       f.rrf::float           AS rrf_score
FROM fused f
JOIN rag.chunks c ON c.id = f.id
{_JOIN_PROVENANCE}
ORDER BY {order}
LIMIT %(top_k)s
"""
    return sql, params


def run_search(
    conn: psycopg.Connection,
    spec: SearchSpec,
    query_vector: list[float] | None,
    sql_timeout_ms: int,
) -> list[dict[str, Any]]:
    sql, params = build_search_sql(spec, query_vector)
    # SET cannot take bind parameters; set_config(name, value, is_local=true)
    # scopes each knob to this transaction.
    with conn.transaction():
        conn.execute("SELECT set_config('statement_timeout', %s, true)", (f"{sql_timeout_ms}ms",))
        if spec.mode != "lexical":
            conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(spec.ef_search),))
            # pgvector >= 0.8: keep scanning when the collection filter
            # discards candidates, instead of returning fewer than LIMIT.
            try:
                with conn.transaction():
                    conn.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
            except psycopg.Error:
                pass
        rows = conn.execute(sql, params).fetchall()
    return [_shape(r) for r in rows]


def _shape(r: dict[str, Any]) -> dict[str, Any]:
    scores = {
        "lexical": r.pop("lexical_score"),
        "dense": r.pop("dense_score"),
        "rrf": r.pop("rrf_score"),
        "rerank": None,
    }
    r["scores"] = scores
    return r
