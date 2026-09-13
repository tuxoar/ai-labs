"""Runtime settings — everything comes from env so no secret ever lands in git.

Typical workstation setup (port-forwards into the cluster):
    kubectl -n basic-ai-platform port-forward svc/litellm  14000:4000 &
    kubectl -n basic-ai-platform port-forward svc/postgres 15432:5432 &
    export RAG_GATEWAY_KEY=$(kubectl -n basic-ai-platform get secret basic-ai-platform-secrets \
        -o jsonpath='{.data.openwebuiRagApiKey}' | base64 -d)
    export RAG_PG_PASSWORD=...   # rag_ingest role password
"""

import os
from dataclasses import dataclass, field

EMBEDDERS = {
    # gateway model alias -> (chunks column, dimensions)
    "embed-nomic": ("emb_nomic", 768),
    "embed-bge-m3": ("emb_bgem3", 1024),
}


@dataclass
class Settings:
    gateway_url: str = field(default_factory=lambda: os.getenv("RAG_GATEWAY_URL", "http://localhost:14000/v1"))
    gateway_key: str = field(default_factory=lambda: os.getenv("RAG_GATEWAY_KEY", ""))
    pg_host: str = field(default_factory=lambda: os.getenv("RAG_PG_HOST", "localhost"))
    pg_port: int = field(default_factory=lambda: int(os.getenv("RAG_PG_PORT", "15432")))
    pg_db: str = field(default_factory=lambda: os.getenv("RAG_PG_DB", "knowledge"))
    pg_user: str = field(default_factory=lambda: os.getenv("RAG_PG_USER", "rag_ingest"))
    pg_password: str = field(default_factory=lambda: os.getenv("RAG_PG_PASSWORD", ""))
    embed_batch_size: int = field(default_factory=lambda: int(os.getenv("RAG_EMBED_BATCH", "16")))
    # Open WebUI (Phase 2 webui-setup command)
    webui_url: str = field(default_factory=lambda: os.getenv("RAG_WEBUI_URL", "https://ai.nuahs.net"))
    webui_token: str = field(default_factory=lambda: os.getenv("RAG_WEBUI_TOKEN", ""))

    @property
    def pg_dsn(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password}"
        )
