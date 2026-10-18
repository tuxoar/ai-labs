# RAG Knowledge Pipeline — scale-first implementation (Weeks 2–3+)

**Revision 2 — 2026-10-18.** Phases 1–2 are live. The top-level plan's
Weeks 2–3 section was strengthened on 2026-09-13 (hierarchy + parent
expansion, a *required* reranker, a ≥50-question golden set, nine security
tests, a ColBERT experiment, and an agent-tool contract). Phases 3–8 below
absorb that spec; the original Phases 3–6 are superseded. See
[Spec reconciliation](#spec-reconciliation) for the mapping.

## Status (as of 2026-10-18)

| Phase | State | Evidence |
|---|---|---|
| 1 — schema, roles, ingestion | ✅ live 2026-09-12 | migrations 001–004 applied; roles `rag_ingest`/`rag_read`; 18 No Starch EPUBs × 3 collections ≈ 43k chunks (`lib-nomic-1000`, `lib-nomic-1000-ctx`, `lib-bgem3-1000`); ingest spend ≈ $0.94 nominal on the `openwebui-rag` key |
| 2 — Open WebUI Track A | ✅ live 2026-09-12 | external pgvector connection on the `rag_read` DSN; knowledges for both nomic collections; retrieval verified with chapter-level citations |
| 3–8 | ⏳ not started | `api/`, `eval/`, `security/` are empty directories |

**Carry-overs from Phases 1–2** (do not lose these):

- Migration 004 is a compat shim for an upstream bug (Open WebUI binds the
  query vector as `float8[]`; open-webui#26663, fix PR #28363). It forces a
  seq scan on Track A. Drop 004 and bump the pin when a release carries the
  fix. Track B binds typed vectors and uses HNSW.
- The Open WebUI admin API token used during `webui-setup` was passed
  through chat — **rotate it** before Phase 3 ships anything that reads it.
- `prompt_guard` enforces on completions only; embedding and rerank calls
  are flag-only (security books tripped it during ingest). The rerank path
  in Phase 4 inherits this.
- Open WebUI's global `RAG_EMBEDDING_MODEL` is nomic/768, so bge-m3 is
  deliberately not wired to the UI; per-embedder comparisons go through
  rag-api, which embeds per request.
- The corpus manifest (titles included) and role passwords are gitignored
  and stay that way.

## Context

Week 1's hardening is done. Next is the learning plan's RAG build — but the user has upgraded its mission: **this is a real, long-term pipeline that will eventually ingest thousands of their ebooks.** Architecture must not be compromised for the timebox. The original "let Open WebUI's knowledge feature do everything" design is therefore rejected: its in-process BM25 (chunks in pod RAM), env-global chunking, and per-file API ingestion don't survive thousands of books.

**Key enabler (verified in v0.11.0 source):** Open WebUI supports **external knowledge connections with `pgvector` as a provider** — it runs a dense `<=>` KNN against an arbitrary external table (configurable `table_name`, `collection_field`, `content_field`, `vector_field`, `metadata_field`, `document_id_field`), embedding the query through its configured RAG embedding engine (= LiteLLM), and renders citations natively. So: **we own the schema and the ingestion pipeline; Open WebUI is just one consumer.**

This design also dissolves three of the four earlier feasibility flags: hybrid search becomes TRUE in-database tsvector + RRF (our SQL — matching the learning plan's original prose), `hnsw.ef_search` is ours to SET per session (ablation restored), and Open WebUI's hybrid/reranker coupling is irrelevant (its internal RAG path goes unused). The remaining flag stands: embedding inversion stays a qualitative demo (no public inverter for nomic/bge-m3).

**User decisions:** corpus = user's own EPUBs (start 3–5, design for thousands) — **never committed to the public repo**; promptfoo for evals; dedicated embed-scoped key.

**Operating principle for everything below: retrieve narrowly, read broadly.**
Passage-level retrieval finds the evidence; hierarchy lets the caller (chat
today, an agent in Month 2) deliberately widen to the section or chapter.

## Architecture

```
EPUBs (workstation)
  → rag-pipeline CLI: parse → chapters → sections (heading tree) → passages
    (structure-aware chunking, ±contextual headers; parents retained)
  → embeddings via LiteLLM (scoped key `openwebui-rag`: embed models only; budgeted, audited)
  → own schema in Postgres `knowledge` DB (COPY-batched, content-hash idempotent, resumable)

Retrieval:
  Track A (live): Open WebUI external knowledge connection (provider=pgvector,
           read-only DB role) → dense KNN on our views → native citations in chat
  Track B (Phase 3+): rag-api FastAPI service in-namespace
           search  = lexical | dense | hybrid (RRF) → optional rerank (top 30–50 → top k)
                     → optional parent expansion (passage → section → chapter), capped
           read    = passage / section / chapter by id, with provenance
           used by the eval harness, the security tests, and (Month 2) the MCP server
  Reranker (Phase 4): separate model-serving path (cross-encoder), reached THROUGH
           LiteLLM as a `rerank` model so key scoping, budgets and audit still apply
  Late interaction (Phase 6): ColBERT-style index on the workstation, same golden set,
           compared — not deployed unless it earns it
```

**Schema (migrations in-repo, applied via psql):**
- `rag.books(id, title, author, source_hash, ingested_at, meta jsonb)` — live
- `rag.chunks(id uuid pk, collection_name, book_id, chapter, seq, text, content_hash, meta jsonb, tsv GENERATED, emb_nomic vector(768), emb_bgem3 vector(1024))` — live; HNSW per embedding column, GIN on `tsv`, btree on `collection_name`
- **Phase 3 additions (migration 005, additive and nullable so existing collections keep working):**
  `rag.chapters(id, book_id, seq, title, text_md, meta)`,
  `rag.sections(id, chapter_id, seq, heading, depth, text_md, meta)`,
  and `rag.chunks.chapter_id`, `rag.chunks.section_id` FKs. Parent text is
  stored once per level; passages reference upward. Collections ingested
  before 005 have NULL parents — the eval matrix uses post-005 collections
  for the parent-expansion rows.
- Views per (collection, embedder) for Open WebUI's field names — live
  (`rag.owui_nomic`, `rag.owui_bgem3`); extend `vmetadata` with
  `section`/`passage_id` once 005 lands so Track A citations deepen for free.
- **DB roles**: `rag_ingest` (insert/update on rag schema — pipeline), `rag_read` (SELECT only — Open WebUI external connection + rag-api). Write-path control the threat model records.

**Scale posture from day 1:** content-hash idempotency + resume state; COPY batching; embedding throughput budgeted against the gateway key's TPM; pgvector storage math documented (≈5k books ≈ 2–3M chunks; nomic 768 float32 ≈ 9–12 GB + HNSW — PVC headroom check; `halfvec` noted); per-collection ingestion so re-embedding/re-chunking is a new collection, not a migration.

## Agent tool contract (fixed now, exposed via MCP in Month 2)

rag-api's HTTP surface IS the tool contract; the Month-2 MCP server wraps it
1:1. Search and read are separate on purpose: an agent gets a small candidate
set and must ask for more context explicitly.

| Tool | rag-api endpoint | Notes |
|---|---|---|
| `search_library(query, filters, top_k)` | `POST /search` | `mode=lexical\|dense\|hybrid`, `embedder`, `ef_search`, `rerank`, `expand=none\|section\|chapter`, `filters={collection, book_id, author}`; `top_k ≤ 50` server-side |
| `read_passage(passage_id)` | `GET /passages/{id}` | passage text + neighbours ±1 (same section) |
| `read_section(section_id)` | `GET /sections/{id}` | capped at `max_context_chars` (config, default 32k); response says if truncated |
| `read_chapter(chapter_id)` | `GET /chapters/{id}` | same cap; chapter > cap returns section list instead of text |
| `search_metadata(author, title, topic)` | `GET /books` | catalog search, no embeddings |

Every result carries **provenance**: `passage_id, section_id, chapter_id,
book_id, book, author, chapter, section, seq, collection, scores{lexical,
dense, rrf, rerank}`. Every request is **bounded**: server-side `top_k`
and context caps, per-request timeout (embedding 10s, SQL 5s via
`statement_timeout`, rerank 15s), and an **audit line** (JSON: caller
identity, operation, filters, result count, bytes returned, latency) —
the same shape as the gateway's guardrail audit so Loki queries line up.
Auth now = static bearer token from a new Secret key; workload identity is
Project 2's job and the threat model says so.

## Phases (~3 weeks honest for 3–8; Track B usable end of Phase 3)

### Phase 1 — Schema, key, pipeline core ✅ (shipped 2026-09-12)
Delivered as planned: `migrations/001–003` (+ `004` upstream compat shim), `apply-migrations.sh`, `pipeline/` (parse, chunk, embed, load, webui, cli), `corpus/manifest.yaml` (gitignored) with the three-variant matrix, `openwebui-rag` scoped key. Verified: idempotent migrations, hash-skip re-runs, SpendLogs rows under the rag key.

### Phase 2 — Open WebUI wiring, Track A ✅ (shipped 2026-09-12)
Delivered: chart RAG env (engine/model/batch/key), `webui-setup` idempotent admin-API wiring, knowledges for both nomic collections, retrieval verified with citations. Three real-world fixes landed from the first ingest (float8[] shim, guardrail scoped to completions, `aembedding` call_type match) and the upstream bug was confirmed and the fix PR endorsed.

### Phase 3 — Hierarchy + rag-api hybrid search (Days 1–5)
- **Migration 005** (chapters, sections, parent FKs) and `parse.py`/`chunk.py` extended to build the section tree from the per-chapter markdown headings (h2/h3; fall back to one section per chapter when a chapter has no headings — many of these books do in places). Record `depth` so parent expansion can stop at the right level.
- **Re-ingest into post-005 collections** (`lib-nomic-1000-h`, `lib-nomic-1000-ctx-h`, `lib-bgem3-1000-h`): the new-collection rule, not an in-place migration. Compare structure-aware section splits against the current paragraph packing in the Phase 5 matrix. Budget: ~$1 nominal on the rag key, as before.
- `api/`: FastAPI with the endpoints in the tool-contract table. Hybrid is one SQL statement: dense KNN with `SET LOCAL hnsw.ef_search`, `ts_rank_cd` candidates, RRF (k=60); `mode` selects which legs run. Query embedding through the gateway on the rag key. Parent expansion reads `rag.sections`/`rag.chapters` under the context caps. `rerank=true` returns 501 until Phase 4.
- Deploy per house style: non-root Dockerfile → **ghcr.io/tuxoar/rag-api** built, scanned and digest-pinned by CI; `templates/rag-api.yaml` (securityContext baseline, resources, `automountServiceAccountToken: false`); CNP: ingress from open-webui (future pipe) and the smoke-test job, egress to postgres:5432, litellm:4000, DNS only; **add `ghcr.io/tuxoar/` to the `allowed-registries` rule in `templates/kyverno-policies.yaml`** (visible policy change in git); image into the Trivy matrix; bearer token as a new Secret key via the Vault path.
- Verify: `/search` returns fused results with full provenance; `expand=section` returns the containing section and respects the cap; ef_search sweep changes recall measurably on a 10-question scratch set; Kyverno policyreports stay clean; audit lines reach Loki.

### Phase 4 — Reranker service + parent expansion tuning (Days 6–9)
- **Serve a cross-encoder as its own path.** Default: `BAAI/bge-reranker-v2-m3` on Hugging Face `text-embeddings-inference` (TEI). Placement decision recorded in the README: (a) in-cluster on CPU (TEI CPU image, ~1.1 GB model, rerank 50 passages in low seconds — acceptable for eval and chat), or (b) on senai next to Ollama with the GPU, reached through the existing 11434-style pinhole pattern (new port, new CNP + ufw rule). Start with (a); move to (b) only if measured latency hurts. **OFFLINE_MODE applies**: weights provisioned explicitly (init container from a pinned artifact or baked image) — never downloaded at runtime.
- **Register it in LiteLLM as a `rerank` model** (`rerank-bge-m3`) on the `openwebui-rag` key with nominal pricing, so reranking is budgeted and audited like everything else and the WebUI chat key cannot call it (smoke-test negative). `prompt_guard` already treats rerank as flag-only.
- rag-api: `rerank=true` retrieves top 30–50 then reranks to `top_k`; rerank scores join the provenance block. Tune expansion policy (how many top hits expand, section vs chapter) against the Phase 5 context-precision numbers rather than by feel.
- Verify: rerank model answers through the gateway only; rag-api p95 with rerank recorded; CNP/Kyverno clean for the new pod.

### Phase 5 — Retrieval evaluation as an experiment (Days 10–14)
- `eval/golden.yaml`: **≥50 questions** over the 18 books, versioned, each tagged with a `kind` and a reference locator (`book`, `chapter`, `section` or passage text snippet) so deterministic metrics can score retrieval without an LLM. Kind quotas: exact terms/names/quotes/identifiers ≥10, paraphrased/semantic ≥10, single-passage obscure facts ≥8, multi-passage within a book ≥6, multi-book ≥6, conflicting-viewpoint ≥4, deliberately unanswerable ≥6. Committed (facts and minimal quotes only — no corpus text beyond what citation needs).
- **Deterministic retrieval metrics first:** `eval/score.py` computes Recall@5/10, MRR, nDCG@10, context precision/recall from rag-api results versus the reference locators. **LLM-judge metrics second** (promptfoo asserts via the gateway `smoke-test` key + `qwen3`): answer faithfulness, citation correctness. Latency p50/p95 from the harness; index size from `pg_relation_size` per collection/index. Judge scores never replace the deterministic numbers.
- Two promptfoo providers: `rag-api` (retrieval-only, every knob a test var) and `openwebui` (end-to-end user path with citations; verify sources via `retrieve-test`, since `/api/chat/completions` returns none).
- `eval/run-matrix.sh` — no pod rolls needed; knobs are rag-api params or collections. Publish the ablation table in the README with exactly these rows: lexical only · dense only · hybrid+RRF · +contextual headers · +reranker · +parent expansion · ColBERT (Phase 6). Plus an **ef_search sweep** (recall vs latency) and the **nomic vs bge-m3** embedder column.
- CI: `rag-eval` workflow_dispatch job (cluster-gated) — the seed of evals as a regression suite for Project 3.

### Phase 6 — Late-interaction experiment (Days 15–16, stretch-but-planned)
- ColBERT-style index over the same corpus on the workstation (RAGatouille / colbert-ai with a small ColBERT checkpoint; model artifact provisioned explicitly). Not deployed to the cluster.
- Run the Phase 5 golden set through it; record retrieval quality, index size, ingestion cost/time, query latency and operational complexity against hybrid+reranker. Write the when-is-it-worth-it conclusion. If it clearly wins on the multi-passage kinds, open a follow-up for a served path; otherwise it stays a documented comparison.

### Phase 7 — Adversarial security tests (Days 17–19)
`security/` — runnable, machine-readable verdicts, each mapped to OWASP LLM08:2025 and the relevant ASI category. Nine tests:
1. `01_poisoned_ebook.py` — injection-laced EPUB (blocking-tier + flag-tier strings) into an isolated collection; force retrieval via both tracks; measure ASR (blocked / flagged / obeyed) using the guardrail's SpendLogs verdict and audit lines.
2. `02_cross_user_leakage.py` — WebUI users A/B on different collections; adversarial cross-queries; document that `rag_read` sees every collection (isolation is app/collection-layer; schema-per-tenant is the future control — register entry).
3. `03_embedding_inversion.py` — export vectors via psql; qualitative attribution/NN-leakage demo with citations (vec2text, ALGEN, secure-RAG survey); define the storage/access boundary.
4. `04_write_path_acl.py` — write-path matrix: WebUI non-admin uploads, external-connection admin gating, `rag_read` INSERT must fail, rag-api has no write endpoints, ingest requires the `rag_ingest` role and the rag key.
5. `05_metadata_poisoning.py` — attacker-controlled title/author/chapter/contextual header; does it move rankings or corrupt citations? Checks header-injection into the `[Book — Chapter]` prefix specifically.
6. `06_context_flooding.py` — documents engineered to dominate candidate sets (near-duplicate spam, keyword stuffing) and to blow the context cap; verify rag-api caps and timeouts hold, measure tokens/latency impact.
7. `07_reranker_manipulation.py` — passages crafted to score high on the cross-encoder after retrieval; measure rank lift and whether expansion amplifies it.
8. `08_citation_spoofing.py` — retrieved text claiming to be from another book/chapter; does the model mis-attribute? Provenance comes from our metadata, not the passage — prove it.
9. `09_search_loop_abuse.py` — seeds for Project 2: queries/content that would cause repeated searches or runaway expansion; assert rag-api's per-request caps and prepare the per-session budgets the MCP server must enforce.

### Phase 8 — Docs & wrap (Days 20–21)
- `project-1-basic-ai-platform/docs/threat-model.md`: LLM08 row → results-backed; new register rows (collection-layer tenancy; rag-api token auth pending workload identity; reranker path); LLM01 note (guardrail covers retrieved context, measured ASR); architecture diagram gains rag-api, the reranker and the read-only role.
- `rag-pipeline/README.md`: architecture, scale math, run instructions, ablation + ef_search + embedder tables, late-interaction conclusion, security findings, tool contract.
- `Learn_Labs_Plan.md`: tick the Weeks 2–3 deliverable; carry the Project-2 design inputs (tool contract, search-loop budgets, identity gap) into the Month-2 design doc.
- Smoke-test section: rag-api `/healthz` + one `/search`; rag key can embed and rerank; chat key denied for both.
- Housekeeping: drop migration 004 if an Open WebUI release with the fix is out; rotate the admin token if not already done.

## Spec reconciliation

How the strengthened Weeks 2–3 spec in `Learn_Labs_Plan.md` maps onto phases:

| Plan section | Phase | Note |
|---|---|---|
| 1 Structural ingestion (book→chapter→section→passage, parents kept) | 3 | chapter-level today; sections + parent FKs via migration 005 |
| 2 Contextual indexing, measured | 1 (done) + 5 | `-ctx` collections exist; the ablation row measures them |
| 3 Retrieval ladder: lexical, dense, hybrid, reranker, parent expansion, ef_search | 3 + 4 | reranker is required, not stretch |
| 4 Late-interaction experiment | 6 | workstation experiment, compared on the same golden set |
| 5 Evaluation (≥50 Qs, deterministic + judge metrics, ablation table) | 5 | promptfoo + our own scorer |
| 6 Security review (nine threat paths) | 7 | four original tests + five new |
| 7 Retrieval as an agent tool | 3 (contract) → Month 2 (MCP) | contract fixed above |

## Verification (end-to-end)
Ingest N books → chat in Open WebUI with citations (Track A) → rag-api hybrid + rerank + expansion with provenance → eval matrix with defensible deltas across all seven ablation rows → nine security scripts with findings in the threat model → CI green (rag-api and reranker images in the Trivy matrix, Kyverno clean, registry allow-list updated) → re-ingest idempotency proven → ArgoCD Synced/Healthy throughout.

## Risks
| Risk | Mitigation |
|---|---|
| External-connection UX quirks (admin-only config, field mapping) | Per-collection views expose its default field names; `webui.py` scripts setup idempotently — proven in Phase 2 |
| Upstream float8[] bug forces seq scans on Track A | Shim 004 in place; Track B binds typed; drop the shim when the fix ships |
| Reranker on CPU too slow for chat | Measure in Phase 4; GPU placement on senai is the documented fallback |
| Reranker weights at runtime vs OFFLINE_MODE | Provision explicitly (pinned artifact / baked image); never a runtime download |
| Bulk embedding throughput vs GPU box | rag key TPM sized; embed.py batches + backoff; nomic first, bge-m3 as benchmark |
| New public images (rag-api, reranker) | CI builds/pins/scans; Kyverno registry list updated deliberately |
| PVC growth at thousands of books (now with parent text stored too) | storage math in README; `halfvec`, PVC expansion, and section-text compression paths documented before needed |
| Query-embedding model mismatch (WebUI global model vs collection embedder) | Track A pins nomic collections; per-embedder eval goes through rag-api |
| Golden-set leakage of corpus text into the public repo | facts + minimal quotes only; reference by locator, not by passage dump |
| Scope creep vs timebox | Track B usable end of Phase 3; ColBERT (6) is the only phase that may be cut; reranker is not |
