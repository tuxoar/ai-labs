# RAG Knowledge Pipeline — scale-first implementation (Weeks 2–3+)

## Context

Week 1's hardening is done. Next is the learning plan's RAG build — but the user has upgraded its mission: **this is a real, long-term pipeline that will eventually ingest thousands of their ebooks.** Architecture must not be compromised for the timebox. The original "let Open WebUI's knowledge feature do everything" design is therefore rejected: its in-process BM25 (chunks in pod RAM), env-global chunking, and per-file API ingestion don't survive thousands of books.

**Key enabler (verified in v0.11.0 source):** Open WebUI supports **external knowledge connections with `pgvector` as a provider** — it runs a dense `<=>` KNN against an arbitrary external table (configurable `table_name`, `collection_field`, `content_field`, `vector_field`, `metadata_field`, `document_id_field`), embedding the query through its configured RAG embedding engine (= LiteLLM), and renders citations natively. So: **we own the schema and the ingestion pipeline; Open WebUI is just one consumer.**

This design also dissolves three of the four earlier feasibility flags: hybrid search becomes TRUE in-database tsvector + RRF (our SQL — matching the learning plan's original prose), `hnsw.ef_search` is ours to SET per session (ablation restored), and Open WebUI's hybrid/reranker coupling is irrelevant (its internal RAG path goes unused). The remaining flag stands: embedding inversion stays a qualitative demo (no public inverter for nomic/bge-m3).

**User decisions:** corpus = user's own EPUBs (start 3–5, design for thousands) — **never committed to the public repo**; promptfoo for evals; dedicated embed-scoped key.

## Architecture

```
EPUBs (workstation)
  → rag-pipeline CLI: parse → per-chapter markdown → structure-aware chunking (our code)
  → embeddings via LiteLLM (scoped key `openwebui-rag`: embed models only; budgeted, audited)
  → own schema in Postgres `knowledge` DB (COPY-batched, content-hash idempotent, resumable)

Retrieval:
  Track A (ships first): Open WebUI external knowledge connection (provider=pgvector,
           read-only DB role) → dense KNN on our table → native citations in chat
  Track B (our API): rag-api FastAPI service in-namespace → TRUE hybrid SQL
           (dense KNN + tsvector ts_rank + RRF), ef_search per query, filters
           → used by the eval harness; UI integration via an Open WebUI Function/Pipe (stretch)
```

**Schema (migrations in-repo, applied via psql):**
- `rag.books(id, title, author, source_hash, ingested_at, meta jsonb)`
- `rag.chunks(id uuid pk, collection_name text, book_id, chapter, seq, text, meta jsonb, tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED)`
- `rag.embeddings(chunk_id fk, model text, emb vector)` — or per-model columns `emb_nomic vector(768)`, `emb_bgem3 vector(1024)` on chunks (decide in Phase 1; per-model columns simpler for HNSW + the external-connection field mapping; embeddings-table more flexible for future models → **recommend per-model columns now, halfvec/table refactor documented as the >2000-dim escape hatch**)
- Indexes: HNSW per embedding column (m/ef_construction from config), GIN on `tsv`, btree on `collection_name`
- A **view per (collection, embedder)** exposing the external-connection field names (`id, collection_name, text, vector, vmetadata`) so Open WebUI's defaults map cleanly without coupling our schema to it
- **DB roles**: `rag_ingest` (insert/update on rag schema — pipeline), `rag_read` (SELECT only — Open WebUI external connection + rag-api). No more everything-as-superuser; a tenancy/security improvement the threat model records.

**Scale posture from day 1:** content-hash idempotency + resume state; COPY batching; embedding throughput budgeted against the gateway key's TPM (raise the rag key's limits vs the UI key); pgvector storage math documented (≈5k books ≈ 2–3M chunks; nomic 768 float32 ≈ 9GB + HNSW — PVC headroom check; halfvec noted); per-collection ingestion so re-embedding/re-chunking is a new collection, not a migration.

## Phases (~3 weeks honest; core RAG usable end of week 1)

### Phase 1 — Schema, key, pipeline core (Days 1–4)
New top-level **`rag-pipeline/`** (fulfills the plan's `rag-exercise/` deliverable; README says so):
- `migrations/00x_*.sql` (schema above); `apply-migrations.sh` (psql via port-forward, creates roles; passwords via existing gen/Vault flow — new Secret keys `ragIngestPassword`, `ragReadPassword` added to Vault path + `templates/secrets.yaml` optional keys, same pattern as the virtual keys)
- `pyproject.toml` (uv; httpx, ebooklib, beautifulsoup4, markdownify, psycopg[binary], pyyaml, typer)
- `pipeline/`: `parse.py` (EPUB→chapters), `chunk.py` (structure-aware; fixed-size fallback; `--contextual-headers`), `embed.py` (gateway client, batching, retry/rate-limit aware), `load.py` (COPY upserts by hash), `cli.py` (`rag ingest --corpus manifest.yaml --collection <name>`)
- `corpus/manifest.yaml` (books metadata + variant matrix → collection names); `.gitignore`: EPUBs, derived markdown, any extracted text
- `provision-keys.sh`: add `openwebui-rag` key (models: embed-nomic, embed-bge-m3; TPM sized for bulk ingest; modest $ budget) → Secret key `openwebuiRagApiKey`. Do NOT touch the `openwebui` chat key (smoke-test 7b guards it).
- Verify: migrations idempotent; ingest 1 book → chunk counts via psql; SpendLogs rows under `key_alias=openwebui-rag`; re-run = no-op (hash skip).

### Phase 2 — Open WebUI wiring, Track A (Days 5–7)
- Chart (`templates/open-webui.yaml` + values): minimal RAG env — `RAG_EMBEDDING_ENGINE=openai`, `RAG_EMBEDDING_MODEL=embed-nomic`, `RAG_EMBEDDING_BATCH_SIZE`, `RAG_OPENAI_API_KEY` ← `openwebuiRagApiKey` (base URL already defaults to litellm). **No `VECTOR_DB` switch, no hybrid env, no memory bump** — internal RAG store stays unused. Env renders after `bap.postgresEnv` include.
- `pipeline/webui.py`: idempotent setup via admin API — create external connection (provider=pgvector, endpoint = read-only DSN using `rag_read`), create knowledge entries mapped to our per-collection views, field mapping config.
- Rollout: Vault-first (rag key + role passwords) → push env change → open-webui rolls (startupProbe) → smoke-test green incl. 7b.
- Verify: chat with the knowledge attached returns answers WITH citations; retrieval query visible in postgres logs hitting our view; Hubble quiet (CNP already allows webui→postgres+litellm — no policy change).

### Phase 3 — rag-api + true hybrid (Days 8–11)
- `rag-pipeline/api/`: FastAPI, endpoints `POST /search` (params: collection, mode=dense|bm25|hybrid, top_k, ef_search, embedder) and `GET /healthz`; hybrid = one SQL: dense KNN (`SET LOCAL hnsw.ef_search`) + `ts_rank_cd` candidates + RRF (k=60). Query embedding via gateway (rag key). Auth: static bearer token (new Secret key) — good enough now; SPIFFE story belongs to Project 2.
- Containerize + deploy per house style: Dockerfile (non-root, distroless-ish), image → **ghcr.io/tuxoar/rag-api** (CI build/push + digest pin; **add `ghcr.io/tuxoar/` to the Kyverno restrict-registries allow-list**), `templates/rag-api.yaml` (deployment/service, securityContext baseline, resources, automount=false), CNP: rag-api ingress from open-webui (future Track B) + egress to postgres:5432, litellm:4000, DNS. CI: helm/kubeconform covers new template automatically; add image to trivy matrix.
- Verify: /search returns fused results with correct citations metadata; ef_search sweep changes recall measurably; Kyverno policyreports stay clean (new pod passes digests/resources/non-root).

### Phase 4 — Eval harness, promptfoo (Days 12–15)
- `eval/golden.yaml`: 25–50 Q/A on the user's books (question, ground_truth, reference_context=chapter, kind incl. ~5 out-of-corpus refusal probes). Committed (facts, minimal quotes).
- Two promptfoo providers: (1) `rag-api` provider — retrieval-only metrics + full control (mode/top_k/ef_search/embedder per test var); (2) `openwebui` provider — end-to-end user path with citations (`POST /api/chat/completions` with knowledge attached). Judge = gateway `smoke-test` key + `qwen3`. Asserts: context-faithfulness, answer-relevance, context-recall, context-relevance.
- `run-matrix.sh` over manifest variants — **no pod rolls needed** (all knobs are rag-api params or separate collections): chunking (fixed vs per-chapter ± contextual headers), dense vs bm25 vs hybrid, top_k sweep, ef_search sweep, embedder nomic vs bge-m3. Results tables → README.
- CI: `rag-eval` workflow_dispatch job (cluster-gated), seed of "evals as regression suite".

### Phase 5 — Adversarial security tests (Days 16–18)
`rag-pipeline/security/` — runnable, machine-readable verdicts:
1. `01_poisoned_ebook.py` — injection-laced EPUB (blocking-tier + flag-tier strings), ingest to isolated collection, force retrieval via both tracks; measure ASR (blocked/flagged/obeyed) — prompt_guard sees retrieved context in the assembled prompt; cross-check SpendLogs verdict metadata + audit lines.
2. `02_cross_user_leakage.py` — webui users A/B with private knowledge on different collections; adversarial cross-queries; PLUS the new angle: verify `rag_read` role can read every collection (document: isolation is app/collection-layer; DB-level per-tenant isolation = future schema-per-tenant; register entry).
3. `03_embedding_inversion.py` — psql-export vectors; qualitative attribution/NN-leakage demo + ALGEN/vec2text/secure-RAG-survey citations.
4. `04_write_path_acl.py` — write-path matrix: webui non-admin uploads, external-connection admin-gating, `rag_read` INSERT attempt (must fail — the new DB-role control demonstrated), rag-api has no write endpoints.

### Phase 6 — Docs & wrap (Days 19–21)
- `threat-model.md`: LLM08 row → results-backed; new register rows (collection-layer tenancy; rag-api token auth pending workload identity); LLM01 note (guardrail covers retrieved context, measured ASR); architecture diagram gains rag-api + rag schema + read-only role.
- `rag-pipeline/README.md`: architecture, scale math, run instructions, eval tables, ablations, security findings; correct the learning plan's tsvector/RRF prose (now actually true — in OUR retrieval, not Open WebUI's).
- `Learn_Labs_Plan.md`: tick deliverable; note the scope upgrade (exercise → long-term pipeline).
- Optional smoke-test section: rag-api /healthz + one /search; rag key embeds OK; chat key still denied bge-m3.

## Verification (end-to-end)
Ingest N books → chat in Open WebUI with citations (Track A) → eval matrix via rag-api with defensible deltas → four security scripts with findings in the threat model → CI green (new image in trivy matrix, Kyverno clean, registry allow-list updated) → re-ingest idempotency proven → ArgoCD Synced/Healthy throughout.

## Risks
| Risk | Mitigation |
|---|---|
| External-connection UX quirks (admin-only config, field mapping) | Per-collection views expose its default field names; `webui.py` scripts setup idempotently |
| Bulk embedding throughput vs GPU box | rag key TPM sized; embed.py batches + backoff; nomic first (fast), bge-m3 as benchmark |
| New public image (ghcr.io/tuxoar/rag-api) | CI builds/pins/scans it; Kyverno registry list updated deliberately (policy change is visible in git) |
| PVC growth at thousands of books | storage math in README; halfvec + PVC expansion path documented before it's needed |
| Query-embedding model mismatch (webui global RAG_EMBEDDING_MODEL vs collection embedder) | Track A pins nomic collections; per-embedder eval goes through rag-api which embeds per request |
| Scope creep vs timebox | Track A usable end of week 1; Track B UI pipe, CronJob ingestion, reranker all explicitly stretch |
