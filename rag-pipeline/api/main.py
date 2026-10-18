"""rag-api: Track B retrieval over the rag schema and the agent tool contract.

    POST /search            search_library(query, filters, top_k)
    GET  /passages/{id}     read_passage
    GET  /sections/{id}     read_section
    GET  /chapters/{id}     read_chapter
    GET  /books             search_metadata(author, title, topic)
    GET  /collections       corpus inventory (eval harness)
    GET  /healthz           liveness/readiness (no auth)

Every authenticated request emits ONE JSON audit line to stdout (caller,
operation, bounds, counts, bytes, latency — never the query text, which stays
inside the Postgres boundary like prompts do), the same discipline as the
gateway guardrail. Connects as the read-only role; there are no write routes.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, field_validator

from . import reads
from .config import EMBEDDERS, ApiSettings
from .retrieval import MODES, SearchSpec, run_search

settings = ApiSettings()
_bearer = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = ConnectionPool(
        settings.pg_conninfo,
        min_size=settings.pool_min,
        max_size=settings.pool_max,
        kwargs={"row_factory": dict_row},
        open=True,
    )
    app.state.http = httpx.Client(
        base_url=settings.gateway_url,
        headers={"Authorization": f"Bearer {settings.gateway_key}"},
        timeout=settings.embed_timeout_s,
    )
    try:
        yield
    finally:
        app.state.http.close()
        app.state.pool.close()


app = FastAPI(title="rag-api", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)


# --- auth + audit -------------------------------------------------------------

def caller(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if not settings.tokens:
        raise HTTPException(503, "rag-api has no API tokens configured")
    if creds is None or creds.credentials not in settings.tokens:
        raise HTTPException(401, "invalid or missing bearer token")
    return settings.tokens[creds.credentials]


def audit(**fields: Any) -> None:
    line = {"event": "rag_api_request", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    print(json.dumps(line, default=str), file=sys.stdout, flush=True)


def _validate_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(422, "id must be a UUID") from None


# --- models -------------------------------------------------------------------

class Filters(BaseModel):
    book_id: str | None = None
    author: str | None = Field(None, max_length=200)

    @field_validator("book_id")
    @classmethod
    def _uuid(cls, v: str | None) -> str | None:
        return _validate_uuid(v) if v else None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    collection: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    mode: Literal["lexical", "dense", "hybrid"] = "hybrid"
    embedder: str = "embed-nomic"
    top_k: int = Field(10, ge=1)
    candidates: int = Field(50, ge=1, description="per-leg candidate pool before fusion")
    ef_search: int = Field(100, ge=10, le=1000)
    rrf_k: int = Field(60, ge=1, le=1000)
    rerank: bool = False
    expand: Literal["none", "section", "chapter"] = "none"
    expand_top: int = Field(3, ge=1)
    filters: Filters = Field(default_factory=Filters)

    @field_validator("embedder")
    @classmethod
    def _embedder(cls, v: str) -> str:
        if v not in EMBEDDERS:
            raise ValueError(f"embedder must be one of {list(EMBEDDERS)}")
        return v


# --- helpers ------------------------------------------------------------------

def embed_query(request: Request, model: str, text: str) -> list[float]:
    try:
        resp = request.app.state.http.post("/embeddings", json={"model": model, "input": [text]})
    except httpx.TimeoutException:
        raise HTTPException(504, "embedding gateway timeout") from None
    except httpx.HTTPError as e:
        raise HTTPException(502, f"embedding gateway error: {e.__class__.__name__}") from None
    if resp.status_code == 400:
        # The gateway guardrail flags (does not block) embeddings; a 400 here
        # is a genuine request error — surface it without the upstream body.
        raise HTTPException(400, "embedding request rejected by gateway")
    if resp.status_code != 200:
        raise HTTPException(502, f"embedding gateway returned {resp.status_code}")
    return resp.json()["data"][0]["embedding"]


def _bytes(obj: Any) -> int:
    return len(json.dumps(obj, default=str).encode())


# --- routes -------------------------------------------------------------------

@app.get("/healthz")
def healthz(request: Request) -> dict[str, str]:
    try:
        with request.app.state.pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception as e:  # noqa: BLE001 — any DB failure is "not ready"
        raise HTTPException(503, f"database unavailable: {e.__class__.__name__}") from None
    return {"status": "ok"}


@app.post("/search")
def search(body: SearchRequest, request: Request, who: str = Depends(caller)) -> dict[str, Any]:
    t0 = time.perf_counter()
    if body.rerank:
        # Phase 4 wires the cross-encoder path (through the gateway).
        raise HTTPException(501, "rerank is not available yet (Phase 4)")
    top_k = min(body.top_k, settings.max_top_k)
    candidates = max(min(body.candidates, settings.max_candidates), top_k)
    expand_top = min(body.expand_top, settings.max_expand)

    timing: dict[str, float] = {}
    qvec = None
    if body.mode != "lexical":
        t = time.perf_counter()
        qvec = embed_query(request, body.embedder, body.query)
        timing["embed_ms"] = round((time.perf_counter() - t) * 1000, 1)

    spec = SearchSpec(
        query=body.query,
        collection=body.collection,
        mode=body.mode,
        embedder=body.embedder,
        top_k=top_k,
        candidates=candidates,
        ef_search=body.ef_search,
        rrf_k=body.rrf_k,
        book_id=body.filters.book_id,
        author=body.filters.author,
    )
    t = time.perf_counter()
    status = 200
    results: list[dict[str, Any]] = []
    expansions: list[dict[str, Any]] = []
    try:
        with request.app.state.pool.connection() as conn:
            results = run_search(conn, spec, qvec, settings.sql_timeout_ms)
            if body.expand != "none" and results:
                expansions = reads.expand_parents(
                    conn, results, body.expand, expand_top, settings.max_context_chars
                )
    except Exception as e:  # noqa: BLE001
        status = 504 if "statement timeout" in str(e) else 500
        raise HTTPException(status, "retrieval failed" if status == 500 else "retrieval timed out") from None
    finally:
        timing["sql_ms"] = round((time.perf_counter() - t) * 1000, 1)
        timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        audit(
            op="search", caller=who, status=status, collection=body.collection, mode=body.mode,
            embedder=body.embedder if body.mode != "lexical" else None, top_k=top_k,
            candidates=candidates, ef_search=body.ef_search if body.mode != "lexical" else None,
            expand=body.expand, filters=body.filters.model_dump(exclude_none=True),
            query_chars=len(body.query), latency_ms=timing["total_ms"],
            result_count=len(results), expansions=len(expansions),
        )

    payload = {
        "query": body.query,
        "collection": body.collection,
        "mode": body.mode,
        "embedder": body.embedder if body.mode != "lexical" else None,
        "bounds": {"top_k": top_k, "candidates": candidates, "ef_search": body.ef_search,
                   "max_context_chars": settings.max_context_chars},
        "results": results,
        "expansions": expansions,
        "timing_ms": timing,
    }
    return payload


def _read(request: Request, who: str, op: str, fn, *args) -> dict[str, Any]:
    t0 = time.perf_counter()
    status = 200
    row = None
    try:
        with request.app.state.pool.connection() as conn:
            with conn.transaction():
                conn.execute("SELECT set_config('statement_timeout', %s, true)", (f"{settings.sql_timeout_ms}ms",))
                row = fn(conn, *args)
        if row is None:
            status = 404
            raise HTTPException(404, "not found")
        return row
    finally:
        audit(op=op, caller=who, status=status, id=args[0] if args else None,
              bytes=_bytes(row) if row else 0, latency_ms=round((time.perf_counter() - t0) * 1000, 1),
              truncated=bool(row.get("truncated")) if isinstance(row, dict) else None)


@app.get("/passages/{passage_id}")
def read_passage(passage_id: str, request: Request, who: str = Depends(caller)) -> dict[str, Any]:
    return _read(request, who, "read_passage", reads.get_passage, _validate_uuid(passage_id))


@app.get("/sections/{section_id}")
def read_section(section_id: str, request: Request, who: str = Depends(caller)) -> dict[str, Any]:
    return _read(request, who, "read_section", reads.get_section, _validate_uuid(section_id), settings.max_context_chars)


@app.get("/chapters/{chapter_id}")
def read_chapter(chapter_id: str, request: Request, who: str = Depends(caller)) -> dict[str, Any]:
    return _read(request, who, "read_chapter", reads.get_chapter, _validate_uuid(chapter_id), settings.max_context_chars)


@app.get("/books")
def books(
    request: Request,
    author: str | None = None,
    title: str | None = None,
    topic: str | None = None,
    limit: int = 50,
    who: str = Depends(caller),
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    t0 = time.perf_counter()
    with request.app.state.pool.connection() as conn:
        rows = reads.search_books(conn, author, title, topic, limit)
    audit(op="search_metadata", caller=who, status=200, result_count=len(rows),
          latency_ms=round((time.perf_counter() - t0) * 1000, 1))
    return {"books": rows}


@app.get("/collections")
def collections(request: Request, who: str = Depends(caller)) -> dict[str, Any]:
    with request.app.state.pool.connection() as conn:
        rows = reads.list_collections(conn)
    audit(op="collections", caller=who, status=200, result_count=len(rows))
    return {"collections": rows}


@app.middleware("http")
async def no_cache(request: Request, call_next) -> Response:
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp
