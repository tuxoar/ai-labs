# rag-pipeline

Scale-first ebook RAG pipeline on the hardened Basic AI Platform. Fulfills the
learning plan's Weeks 2–3 deliverable, architected for the long term
(thousands of books). Full design: [PLAN.md](PLAN.md).

```
EPUBs → parse (chapters → sections via the heading tree)
      → chunk (paragraph packing inside a chapter or a section, ±contextual headers)
      → embeddings via LiteLLM (embed-only scoped key: budgeted, audited)
      → rag schema in Postgres/pgvector: books / chapters / sections / chunks
        (parents stored once, passages point upward; content-hash idempotent)

Retrieval:
  Track A  Open WebUI external knowledge connection (pgvector provider,
           READ-ONLY role) → dense KNN on rag.owui_* views → native citations
  Track B  rag-api: lexical | dense | hybrid (RRF) in one SQL statement,
           per-query ef_search, filters applied before ranking, optional
           parent expansion (passage → section → chapter) under a context cap,
           bounded read endpoints = the agent tool contract (PLAN.md)
```

**Retrieve narrowly, read broadly.** Passage retrieval finds the evidence; the
hierarchy lets the caller widen to the section or chapter on purpose.

## Setup (workstation)

```bash
cd rag-pipeline && uv sync
kubectl -n basic-ai-platform port-forward svc/litellm  14000:4000 &
kubectl -n basic-ai-platform port-forward svc/postgres 15432:5432 &
export RAG_GATEWAY_KEY=$(kubectl -n basic-ai-platform get secret basic-ai-platform-secrets -o jsonpath='{.data.openwebuiRagApiKey}' | base64 -d)
export RAG_PG_PASSWORD=...        # rag_ingest role password

./migrations/apply-migrations.sh  # schema + roles (idempotent)
cp corpus/manifest.example.yaml corpus/manifest.yaml   # edit; NEVER commit
uv run rag ingest --manifest corpus/manifest.yaml   # also upserts chapters/sections, backfills old chunks
uv run rag status                                   # per-collection counts incl. chunks with a section
uv run rag webui-setup --collection lib-nomic-1000 \
  --read-dsn "postgresql://rag_read:<pw>@postgres:5432/knowledge"
```

**The corpus never enters this public repo** — EPUBs, derived text, and
`manifest.yaml` (titles included) are gitignored.

Manifest variants: `split: chapter` (default; Phase-1 behaviour, hash-stable
for the three original collections) or `split: section` (packing stops at
h2/h3 headings; every chunk carries `section_id`). The `*-h` variants in
`manifest.example.yaml` are the section-split twins of the baselines.

## rag-api (Track B)

```bash
cd rag-pipeline && uv sync --extra api
export RAG_PG_HOST=localhost RAG_PG_PORT=15432 RAG_PG_USER=rag_read RAG_PG_PASSWORD=...
export RAG_GATEWAY_URL=http://localhost:14000/v1 RAG_GATEWAY_KEY=$RAG_GATEWAY_KEY
export RAG_API_TOKENS="dev=$(openssl rand -hex 16)"
uv run uvicorn api.main:app --port 8000
curl -s -H "Authorization: Bearer $tok" localhost:8000/search -d '{"query":"...","collection":"lib-nomic-1000-h","mode":"hybrid","expand":"section"}'
```

| Tool (Month-2 MCP) | Endpoint | Knobs / bounds |
|---|---|---|
| `search_library` | `POST /search` | `mode` lexical·dense·hybrid, `embedder`, `top_k` (≤50), `candidates` (≤200), `ef_search` 10–1000, `rrf_k`, `expand` none·section·chapter, `filters.book_id/author`; `rerank` → 501 until Phase 4 |
| `read_passage` | `GET /passages/{id}` | passage + prev/next neighbours |
| `read_section` | `GET /sections/{id}` | capped at `RAG_MAX_CONTEXT_CHARS` (32k), `truncated` flag |
| `read_chapter` | `GET /chapters/{id}` | over the cap → section map instead of text |
| `search_metadata` | `GET /books` | `author`, `title`, `topic` (chapter titles + section headings) |
| — | `GET /collections`, `GET /healthz` | inventory; liveness (no auth) |

Every result carries provenance (`passage_id, section_id, chapter_id, book_id,
book, author, chapter, section, seq, collection, scores{lexical,dense,rrf,rerank}`).
Every authenticated request writes one JSON audit line (caller name from the
token map, operation, bounds, counts, bytes, latency — never the query text).
Postgres role is `rag_read`; there are no write routes. SQL knobs
(`statement_timeout`, `hnsw.ef_search`, `hnsw.iterative_scan`) are set per
transaction via `set_config`.

**Deploy (house style, k8s-first — the Compose variant does not get rag-api):**
CI builds `ghcr.io/tuxoar/rag-api` from this directory on `main` and prints
the digest; pin it in `project-1-basic-ai-platform-k8s/values.yaml`
(`ragApi.image`), add `ragApiTokens` to the Vault path, then flip
`ragApi.enabled: true` in `values-talos.yaml`. The chart ships the
Deployment (non-root 10001, read-only rootfs, no SA token), a ClusterIP
Service, and CNPs (ingress from Open WebUI only; egress to postgres + litellm
+ DNS). `ghcr.io/tuxoar/*` was added to the Kyverno registry allow-list for it.

Tests (`uv run pytest`): parser/chunker hierarchy on synthetic markdown, the
retrieval SQL builder (legs, fusion, filters inside each leg), and rag-api
auth/bounds with the DB and gateway stubbed.

## Scale notes

- Idempotency: books by EPUB sha256, chunks by (collection, content-hash);
  re-runs skip, second embedders fill the empty column.
- Throughput: embedding goes through the gateway key (`openwebui-rag`,
  500k TPM / 120 RPM) with batch + 429 backoff.
- Storage math (before it hurts): ~5k books ≈ 2–3M chunks; nomic-768 float32
  ≈ 9–12 GB vectors + HNSW index — watch the postgres PVC (20Gi on Talos).
  Escape hatches, documented in advance: `halfvec`, or an embeddings
  side-table keyed by (chunk_id, model).
- Re-chunking/re-embedding = a NEW collection, never a schema migration.

## Status

Phases per [PLAN.md](PLAN.md) (revision 2, 2026-10-18):

- [x] Phase 1 — schema, roles, ingestion pipeline (live 2026-09-12)
- [x] Phase 2 — Open WebUI Track A wiring, external pgvector knowledge (live 2026-09-12)
- [~] Phase 3 — section hierarchy (migration 005) + rag-api hybrid search with the agent tool contract — code, chart, CI done 2026-10-18; **pending cluster**: apply 005, re-ingest `*-h` collections, publish image + pin digest, enable
- [ ] Phase 4 — cross-encoder reranker as its own serving path, behind LiteLLM; parent-expansion tuning
- [ ] Phase 5 — promptfoo eval matrix: ≥50-question golden set, deterministic + judge metrics, ablation table (results land here)
- [ ] Phase 6 — ColBERT late-interaction comparison (workstation experiment)
- [ ] Phase 7 — nine adversarial security tests → threat model LLM08
- [ ] Phase 8 — docs wrap
