# rag-pipeline

Scale-first ebook RAG pipeline on the hardened Basic AI Platform. Fulfills the
learning plan's Weeks 2–3 deliverable, architected for the long term
(thousands of books). Full design: [PLAN.md](PLAN.md).

```
EPUBs → parse (chapters) → chunk (structure-aware, ±contextual headers)
      → embeddings via LiteLLM (embed-only scoped key: budgeted, audited)
      → rag schema in Postgres/pgvector (COPY-batched, content-hash idempotent)

Retrieval:
  Track A  Open WebUI external knowledge connection (pgvector provider,
           READ-ONLY role) → dense KNN on rag.owui_* views → native citations
  Track B  rag-api (Phase 3): true in-database hybrid — dense KNN + tsvector
           ts_rank + RRF, per-query ef_search
```

## Setup (workstation)

```bash
cd rag-pipeline && uv sync
kubectl -n basic-ai-platform port-forward svc/litellm  14000:4000 &
kubectl -n basic-ai-platform port-forward svc/postgres 15432:5432 &
export RAG_GATEWAY_KEY=$(kubectl -n basic-ai-platform get secret basic-ai-platform-secrets -o jsonpath='{.data.openwebuiRagApiKey}' | base64 -d)
export RAG_PG_PASSWORD=...        # rag_ingest role password

./migrations/apply-migrations.sh  # schema + roles (idempotent)
cp corpus/manifest.example.yaml corpus/manifest.yaml   # edit; NEVER commit
uv run rag ingest --manifest corpus/manifest.yaml
uv run rag status
uv run rag webui-setup --collection lib-nomic-1000 \
  --read-dsn "postgresql://rag_read:<pw>@postgres:5432/knowledge"
```

**The corpus never enters this public repo** — EPUBs, derived text, and
`manifest.yaml` (titles included) are gitignored.

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

- [x] Phase 1 — schema, roles, ingestion pipeline
- [x] Phase 2 — Open WebUI Track A wiring (external pgvector knowledge)
- [ ] Phase 3 — rag-api (hybrid SQL: dense + BM25/tsvector + RRF, ef_search)
- [ ] Phase 4 — promptfoo eval matrix (results land here)
- [ ] Phase 5 — adversarial security tests → threat model LLM08
- [ ] Phase 6 — docs wrap
