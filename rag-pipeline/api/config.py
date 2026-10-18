"""rag-api settings — all from env (Secret-backed in the chart). The service
connects as the READ-ONLY role `rag_read`; it has no write path by design."""

import os
from dataclasses import dataclass, field

# gateway model alias -> (chunks column, dimensions); mirrors pipeline.config
EMBEDDERS = {
    "embed-nomic": ("emb_nomic", 768),
    "embed-bge-m3": ("emb_bgem3", 1024),
}


def _tokens() -> dict[str, str]:
    """RAG_API_TOKENS="name=token,name2=token2" (preferred: audit lines carry
    the caller name) or RAG_API_TOKEN=token (caller "default"). Returns
    token -> name."""
    out: dict[str, str] = {}
    multi = os.getenv("RAG_API_TOKENS", "")
    for item in filter(None, (s.strip() for s in multi.split(","))):
        name, _, tok = item.partition("=")
        if name and tok:
            out[tok] = name
    single = os.getenv("RAG_API_TOKEN", "")
    if single:
        out[single] = "default"
    return out


@dataclass
class ApiSettings:
    pg_host: str = field(default_factory=lambda: os.getenv("RAG_PG_HOST", "postgres"))
    pg_port: int = field(default_factory=lambda: int(os.getenv("RAG_PG_PORT", "5432")))
    pg_db: str = field(default_factory=lambda: os.getenv("RAG_PG_DB", "knowledge"))
    pg_user: str = field(default_factory=lambda: os.getenv("RAG_PG_USER", "rag_read"))
    pg_password: str = field(default_factory=lambda: os.getenv("RAG_PG_PASSWORD", ""))
    gateway_url: str = field(default_factory=lambda: os.getenv("RAG_GATEWAY_URL", "http://litellm:4000/v1"))
    gateway_key: str = field(default_factory=lambda: os.getenv("RAG_GATEWAY_KEY", ""))
    tokens: dict[str, str] = field(default_factory=_tokens)
    # Bounds — the contract's "every request is bounded" guarantees.
    max_top_k: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_TOP_K", "50")))
    max_candidates: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_CANDIDATES", "200")))
    max_context_chars: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_CONTEXT_CHARS", "32000")))
    max_expand: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_EXPAND", "5")))
    embed_timeout_s: float = field(default_factory=lambda: float(os.getenv("RAG_EMBED_TIMEOUT_S", "10")))
    sql_timeout_ms: int = field(default_factory=lambda: int(os.getenv("RAG_SQL_TIMEOUT_MS", "5000")))
    pool_min: int = field(default_factory=lambda: int(os.getenv("RAG_POOL_MIN", "1")))
    pool_max: int = field(default_factory=lambda: int(os.getenv("RAG_POOL_MAX", "8")))

    @property
    def pg_conninfo(self) -> str:
        return (
            f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
            f"user={self.pg_user} password={self.pg_password} application_name=rag-api"
        )
