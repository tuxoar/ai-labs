"""Track A wiring: register our pgvector schema with Open WebUI as an
external knowledge connection + one knowledge entry per collection.
Idempotent by name. Admin token required (external endpoints are admin-only).

The connection's endpoint is a conninfo DSN for the READ-ONLY role rag_read —
Open WebUI can retrieve chunks but can never write the store (write-path
access control, threat model LLM08)."""

import httpx

from .config import Settings

VIEW_BY_EMBEDDER = {"embed-nomic": "rag.owui_nomic", "embed-bge-m3": "rag.owui_bgem3"}
SOURCE_CONFIG_BASE = {
    "collection_field": "collection_name",
    "content_field": "text",
    "vector_field": "vector",
    "metadata_field": "vmetadata",
    "document_id_field": "id",
}
CONNECTION_NAME = "rag-pipeline (pgvector, read-only)"


def _client(settings: Settings) -> httpx.Client:
    if not settings.webui_token:
        raise SystemExit("RAG_WEBUI_TOKEN not set (Open WebUI admin API token)")
    return httpx.Client(
        base_url=f"{settings.webui_url}/api/v1",
        headers={"Authorization": f"Bearer {settings.webui_token}"},
        timeout=60,
        verify=True,
    )


def ensure_embedding_config(settings: Settings, rag_key: str, model: str = "embed-nomic", batch: int = 16) -> None:
    """Open WebUI PERSISTS RAG settings in its DB after first boot — env vars
    only seed the initial value, so the chart env alone doesn't flip an
    existing install (found live: a 68-day-old instance kept its 384-dim
    all-MiniLM default and broke dimension-matched retrieval). This pushes the
    persisted config via the admin API; idempotent."""
    with _client(settings) as c:
        resp = c.post(
            "/retrieval/embedding/update",
            json={
                "RAG_EMBEDDING_ENGINE": "openai",
                "RAG_EMBEDDING_MODEL": model,
                "RAG_EMBEDDING_BATCH_SIZE": batch,
                "openai_config": {"url": "http://litellm:4000/v1", "key": rag_key},
            },
        )
        resp.raise_for_status()


def ensure_connection(settings: Settings, read_dsn: str) -> str:
    """Create (or reuse by name) the pgvector external connection; returns id."""
    with _client(settings) as c:
        existing = c.get("/knowledge/external/connections")
        existing.raise_for_status()
        for conn in existing.json().get("items", []):
            if conn.get("name") == CONNECTION_NAME:
                return conn["id"]
        resp = c.post(
            "/knowledge/external/connections",
            json={
                "name": CONNECTION_NAME,
                "provider": "pgvector",
                "endpoint": read_dsn,
                "auth_config": {},
                "config": {"timeout": 30},
                "capabilities": {"retrieve": True},
                "enabled": True,
            },
        )
        resp.raise_for_status()
        conn_id = resp.json()["id"]
        test = c.post(f"/knowledge/external/connections/{conn_id}/test")
        test.raise_for_status()
        return conn_id


def ensure_knowledge(
    settings: Settings, connection_id: str, collection: str, embedder: str, description: str = ""
) -> dict:
    """Create a knowledge entry pointing at our per-embedder view, filtered to
    one collection_name. Skips if a knowledge with the same name exists."""
    name = f"books:{collection}"
    with _client(settings) as c:
        listing = c.get("/knowledge/")
        listing.raise_for_status()
        items = listing.json()
        items = items.get("items", items) if isinstance(items, dict) else items
        for k in items:
            if k.get("name") == name:
                return {"id": k["id"], "name": name, "status": "exists"}
        resp = c.post(
            "/knowledge/external/knowledge/create",
            json={
                "name": name,
                "description": description or f"rag-pipeline collection {collection} ({embedder})",
                "connection_id": connection_id,
                "source": {
                    "type": "collection",
                    "name": collection,
                    "config": {**SOURCE_CONFIG_BASE, "table_name": VIEW_BY_EMBEDDER[embedder]},
                },
            },
        )
        resp.raise_for_status()
        return {"id": resp.json()["id"], "name": name, "status": "created"}
