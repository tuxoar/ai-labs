"""Auth + bounds at the HTTP layer with the DB/gateway stubbed out."""

import os

os.environ["RAG_API_TOKENS"] = "eval=tok-eval,smoke=tok-smoke"
os.environ["RAG_MAX_TOP_K"] = "20"

from contextlib import contextmanager  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from api import main  # noqa: E402


class _FakeConn:
    def execute(self, *_a, **_k):
        return self

    def fetchone(self):
        return (1,)

    @contextmanager
    def transaction(self):
        yield


class _FakePool:
    @contextmanager
    def connection(self, timeout=None):
        yield _FakeConn()

    def close(self):
        pass


def _client(monkeypatch):
    client = TestClient(main.app, raise_server_exceptions=True)
    # Replace lifespan-created resources with fakes.
    client.app.state.pool = _FakePool()
    monkeypatch.setattr(main, "embed_query", lambda *_a, **_k: [0.0] * 768)
    monkeypatch.setattr(main, "run_search", lambda conn, spec, vec, t: [
        {"passage_id": "p1", "section_id": None, "chapter_id": None, "book_id": "b", "book": "B",
         "author": "A", "chapter": "C", "section": None, "seq": 1, "collection": spec.collection,
         "text": "t", "scores": {"lexical": None, "dense": 0.9, "rrf": 0.016, "rerank": None},
         "_spec": spec},
    ])
    return client


def test_healthz_is_unauthenticated(monkeypatch):
    with TestClient(main.app) as c:
        c.app.state.pool = _FakePool()
        assert c.get("/healthz").status_code == 200


def test_search_requires_token(monkeypatch):
    c = _client(monkeypatch)
    body = {"query": "x", "collection": "lib"}
    assert c.post("/search", json=body).status_code == 401
    assert c.post("/search", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    r = c.post("/search", json=body, headers={"Authorization": "Bearer tok-eval"})
    assert r.status_code == 200
    assert r.json()["results"][0]["passage_id"] == "p1"


def test_search_bounds_are_server_enforced(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/search", json={"query": "x", "collection": "lib", "top_k": 999, "candidates": 99999},
               headers={"Authorization": "Bearer tok-smoke"})
    assert r.status_code == 200
    spec = r.json()["results"][0]["_spec"]
    assert spec["top_k"] == 20 and spec["candidates"] == 200
    assert r.json()["bounds"]["top_k"] == 20


def test_search_validation(monkeypatch):
    c = _client(monkeypatch)
    h = {"Authorization": "Bearer tok-eval"}
    assert c.post("/search", json={"query": "", "collection": "lib"}, headers=h).status_code == 422
    assert c.post("/search", json={"query": "x", "collection": "bad name"}, headers=h).status_code == 422
    assert c.post("/search", json={"query": "x", "collection": "lib", "embedder": "embed-arctic2"}, headers=h).status_code == 422
    assert c.post("/search", json={"query": "x", "collection": "lib", "ef_search": 5}, headers=h).status_code == 422
    assert c.post("/search", json={"query": "x", "collection": "lib", "rerank": True}, headers=h).status_code == 501
    assert c.get("/passages/not-a-uuid", headers=h).status_code == 422
