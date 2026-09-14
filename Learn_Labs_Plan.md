# AI Security Engineering Learning Plan

## 90-Day Intensive Portfolio Program — 2026 Revision

### Goal

The goal of these labs is to strengthen skills towards being a:

* **Security Engineer at an AI company** (product security for agentic systems, or securing training/inference infrastructure) — *primary target*
* AI Security Engineer
* AI Infrastructure / Platform Engineer
* Staff-Level Platform Security Engineer supporting AI workloads

This plan is optimized around existing strengths:

* Kubernetes (Talos, EKS, kubeadm)
* AWS
* Security Engineering
* Terraform
* GitOps
* Wazuh
* CI/CD
* Platform Engineering

The objective is not to become a data scientist. It is to become the engineer who
can **securely build, sandbox, govern, and operate agentic AI systems** — and who
can speak credibly about securing model weights and AI infrastructure the way AI
labs actually do it.

### What changed in this revision (vs. the 2024-era plan)

The field's security center of gravity moved from RAG to **agents**. OWASP shipped
a dedicated [Top 10 for Agentic Applications (2026)](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/);
MCP became the standard integration layer (and a target-rich attack surface); AI
labs hire security engineers for sandboxing, attestation, egress control, and
model-weight protection. This revision:

1. Adds a **Secure Agent Platform** project (MCP + sandboxing + agent identity) as the centerpiece.
2. Adds a **red-teaming & evals** track — evals as the security regression suite.
3. Adds a **model-weight & infrastructure security** track (RAND SL framework, attestation, egress controls) — the AI-lab-specific material.
4. Reframes the old RAG project as a **Modern Retrieval & Context Engineering Lab**: hybrid retrieval, reranking, hierarchical context, late interaction, and measured retrieval evals — the differentiator is engineering and evaluation, not merely having RAG.
5. Rebuilds the AI SecOps project on the secure-agent foundation, with a published threat model.
6. Updates all study material to OWASP LLM Top 10 (2025), Agentic Top 10 (2026), MITRE ATLAS, and NIST AI RMF.
7. Adds a **visibility layer**: published threat models and write-ups, OSS contributions, responsible disclosure.

---

# Target Portfolio

At the end of 90 days, the portfolio should contain:

1. **Basic AI Platform on Kubernetes** — ✅ built **and hardened** (Compose + Helm/Talos; Week-1 hardening pass completed 2026-09-12, threat model published)
2. **Secure Agent Platform** — MCP servers, sandboxed execution, agent identity *(the differentiator)*
3. **AI Red Team & Eval Harness** — automated injection/jailbreak testing wired into CI
4. **AI Security Operations Platform** — investigation agents built on the secure foundation
5. **Model-Weight Security Lab** — egress controls, attestation, RAND SL mapping *(spans month 3)*
6. **Modern Retrieval & Context Engineering Lab** — hybrid + hierarchical retrieval, reranking, late-interaction experiments, and evals *(2 weeks, folded into Month 1 and consumed by Project 2)*
7. AI Radio Net Logger *(optional)*

Plus **published artifacts**: a threat model per project, blog write-ups, and at
least one upstream contribution or disclosure.

---

# Existing Environment

## Infrastructure

### Talos Kubernetes Cluster

* GitOps managed (ArgoCD app-of-apps)
* Existing observability stack (kube-prometheus-stack)
* Existing security tooling (Wazuh, Vault + VSO, Cilium)

### Local AI Server

* Ollama on RTX 5080 (16 GB) — internal model provider, "local Bedrock equivalent"
* node_exporter + dcgm-exporter for host/GPU metrics
* Consumed by the cluster; model serving stays off-cluster for now

---

# Completed Work & Changes to Current Projects

## Project 1 — Basic AI Platform ✅ (built)

Both variants are done and deployed:

* `project-1-basic-ai-platform` — Docker Compose: Open WebUI → LiteLLM → Ollama,
  Postgres+pgvector, Redis cache, Prometheus/Grafana with GPU observability, smoke tests
* `project-1-basic-ai-platform-k8s` — umbrella Helm chart on Talos via ArgoCD:
  Vault/VSO secrets, ServiceMonitors into kube-prometheus-stack, Cilium Gateway

## Changes to apply to Project 1 — ✅ COMPLETED 2026-09-12 (hardening pass)

Executed end-to-end in one day (planned ~1 week): staged GitOps rollout, every
stage verified live before the next. Scope decision: **k8s-first** — the Talos
deployment got the full pass; the Compose variant got digest pins, the shared
gateway config (guardrail + audit ride along), and docs, and deliberately stays
on the master key (recorded as accepted divergence A5 in the threat model).

### Governance ✅

* Scoped virtual keys minted by an idempotent `scripts/provision-keys.sh`
  (master key retired from Open WebUI): `openwebui` — 12-model allow-list,
  $50/30d budget, 100k TPM / 60 RPM; `smoke-test` — $5/7d. Nominal per-token
  prices on every model make budgets/spend real with free local models.
* Least-privilege demonstrated: the WebUI key cannot reach the benchmark
  embedders (403) or key-management routes (401) — asserted in the smoke test.

### Network security ✅

* **CiliumNetworkPolicies**, default-deny, rolled out allow-first with a Hubble
  DROPPED watch before the catch-all. The headline egress pinhole: **only
  litellm pods may reach `ai-server:11434`**. Negative probes live in the smoke
  test (gateway bypass, lateral movement, general egress — all denied).
* Field lesson: the egress lock hung Open WebUI's startup phone-home (Hubble
  showed the drops) — fixed with `OFFLINE_MODE=true`, the right posture for a
  locked-down namespace.
* ufw active on senai: 11434/9100/9400 allow-listed to the Talos node /30s
  (Cilium masquerades pod egress to node IPs) + workstation; applied ruleset
  recorded in the monitoring doc.

### Policy & supply chain ✅

* **Kyverno 3.9.1** installed via a new ArgoCD app in k8s-gitops; four
  namespaced Policies ship WITH the chart: require-digests,
  restrict-registries, require-resources (deliberately no CPU limits —
  annotated), disallow-root (litellm + open-webui documented exceptions).
  Audit → clean policyreports → **Enforce**, verified by denied admission.
* All images pinned `tag@digest`. Signing reality: only LiteLLM signs
  (key-based, not keyless) — its public key is vendored in-repo and
  **cosign verify is a blocking CI job**; the rest rely on pins + registry
  allow-list + Trivy. `.trivyignore` is the reasoned accepted-CVE register
  (gate = CRITICAL + `--ignore-unfixed`); one real fix shipped via a pin bump
  (open-webui GitPython RCE).
* PSA labels via `managedNamespaceMetadata`: enforce baseline, warn/audit
  restricted. Non-root everywhere images allow (postgres/redis 999,
  prometheus 65534, grafana 472); `automountServiceAccountToken: false` on
  every pod.

### Gateway as security control point ✅

* `prompt_guard.py` heuristic `CustomGuardrail` (pre-call, default-on): blocks
  high-confidence injections (400), flags the rest; structured JSON audit line
  with key attribution; verdict lands in SpendLogs. Guardrail events flow
  through promtail → Loki (no prompt text in the log line — prompts stay in
  the Postgres boundary).
* Full request/response audit in `LiteLLM_SpendLogs`
  (`store_prompts_in_spend_logs`, 90d retention), verified before/after.

### Testing ✅

* GitHub Actions CI: helm lint/template + kubeconform (CRD catalog), compose
  validation, shellcheck, Trivy config + per-image CRITICAL gates with
  CycloneDX SBOM artifacts, blocking cosign verify, and a config-parity check
  keeping the two litellm configs byte-identical. Local mirror:
  `scripts/ci-validate.sh`. Smoke test grew governance negatives, CNP egress
  probes, and tier-3 model timeouts; Month-2 injection-regression hook point
  stubbed.

### Documentation ✅

* `docs/threat-model.md` published: trust boundaries TB1–TB4, OWASP LLM Top 10
  2025 control table, the "Ollama has no auth" rationale (now enforced from
  both sides: CNP pinhole in-cluster, ufw on the LAN), and the
  accepted-risk register (A1 litellm root, A1b open-webui root+offline,
  A5 compose divergence, …). The template for every later project.

**Deferred/follow-ups:** re-sign images into own registry (stretch), migrate
litellm/open-webui to non-root images then PSA enforce→restricted, Kyverno
CEL policy migration, kube-prom Grafana PVC corruption (storage incident that
also forced a Vault rebuild — runbook now in k8s-gitops/docs/vault-setup.md).

---

# Study Track (throughout — replaces the old "AI Security Topics" section)

Master these; they are current as of 2026 and are the interview vocabulary:

## OWASP LLM Top 10 (2025 revision)

Includes categories the old list predates: **System Prompt Leakage**,
**Vector & Embedding Weaknesses**, **Misinformation**, **Unbounded Consumption** —
alongside Prompt Injection, Sensitive Information Disclosure, Supply Chain,
Data/Model Poisoning, Improper Output Handling, Excessive Agency.

## OWASP Top 10 for Agentic Applications (2026)

The new core material (ASI01–ASI10): **Agent Goal Hijack**, **Tool Misuse &
Exploitation**, **Identity & Privilege Abuse**, memory/context poisoning,
cascading failures, **Human-Agent Trust Exploitation**, **Rogue Agents**.
Follow the [OWASP Agentic Security Initiative](https://genai.owasp.org/initiatives/agentic-security-initiative/) —
and look for contribution opportunities (see Visibility).

## Frameworks for staff-level threat modeling

* **MITRE ATLAS** — adversarial ML tactics/techniques; the ATT&CK of AI
* **NIST AI RMF + Generative AI Profile**
* **RAND "Securing AI Model Weights"** — the SL1–SL5 security-level framework AI labs use
* Frontier-lab safety/security frameworks (e.g., Anthropic RSP / ASL levels) — read them; interviewers work under them

---

# Month 1

# Harden the Foundation + Modern Retrieval & Context Engineering

## Week 1 — Project 1 hardening pass ✅ DONE (2026-09-12)

Executed the "Changes to apply to Project 1" list above — see the completion
notes there. Final state: 24/24 smoke checks, Kyverno Enforce with clean
policyreports, CI green, threat model published.

## Weeks 2–3 — Modern Retrieval & Context Engineering Lab

Build a production-style retrieval system over a **large personal ebook corpus** and
benchmark each architectural improvement. The goal is no longer to demonstrate that
you can wire embeddings to a vector database; it is to understand **retrieval quality,
context construction, evaluation, and the security boundaries of a modern context
engine**. This becomes the knowledge/research tool consumed by Project 2.

**Run it THROUGH the platform (not beside it):** keep PostgreSQL + pgvector as the
primary store and route embedding/model calls **through LiteLLM with scoped keys** so
requests remain budgeted, rate-limited, and audit-logged. Preserve Open WebUI as a
simple interactive client, but build the retrieval pipeline as its own service/API so
it can later be exposed safely to agents. `OFFLINE_MODE` remains enabled; model and
embedding dependencies must be explicitly provisioned rather than downloaded at
runtime.

### 1. Structural ingestion — books are not bags of chunks

Normalize EPUB/PDF/TXT into a canonical document model and preserve hierarchy:

```
book → chapter → section → passage
```

Store stable document/parent IDs, title, author, chapter/section headings, source
location/page where available, and the original normalized text. Start with EPUB and
text-native PDF; scanned/OCR-heavy books and MOBI/AZW remain out of scope.

Compare **structure-aware passage splitting** against fixed-token chunking. Do not
throw away parent text after chunking: retrieval should be able to locate a passage
and then expand upward to its section or chapter.

### 2. Contextual indexing

Create a short contextual header for each passage before indexing, e.g. book, chapter,
section, entities/topic, and enough generated context to resolve ambiguous references.
Index the contextualized representation while retaining the original passage as the
citable source. Measure whether contextual enrichment improves retrieval rather than
assuming it does.

### 3. Build a retrieval ladder, not one retriever

Implement and benchmark these stages independently:

1. **Lexical baseline** — PostgreSQL FTS/BM25-style search (`tsvector`/`tsquery`).
2. **Dense baseline** — pgvector + `embed-bge-m3` (keep `embed-nomic` as a comparison).
3. **Hybrid retrieval** — lexical + dense candidates fused with **Reciprocal Rank
   Fusion (RRF)**.
4. **Reranking** — retrieve broadly (e.g. top 30–50), then use a dedicated
   **cross-encoder/BGE reranker service** to produce the final top passages. This is
   required, not stretch; deploying a separate model-serving path is part of the lab.
5. **Hierarchical parent expansion** — after passage retrieval/reranking, expand the
   strongest hits to coherent sections/chapters and let the long-context model read
   broader source material. The operating principle is **retrieve narrowly, read
   broadly**.

Tune pgvector HNSW (`ef_search`) against measured recall/latency instead of choosing a
value by intuition.

### 4. Late-interaction retrieval experiment

Add **ColBERT-style late-interaction retrieval** as the principal stretch experiment.
Run it over the same corpus/eval set and compare it with the pgvector hybrid +
reranker pipeline. Record retrieval quality, index size, ingestion cost, query latency,
and operational complexity. The objective is to understand when token-level late
interaction is worth the storage/serving tradeoff, not to replace pgvector by default.

### 5. Retrieval evaluation as an engineering experiment

Create a versioned golden dataset of at least **50 questions** spanning:

* exact terms, names, quotations, and identifiers (lexical strength)
* semantic/paraphrased questions (dense strength)
* obscure facts located in one passage
* questions whose evidence spans multiple passages/sections
* questions requiring evidence from multiple books
* conflicting authors/viewpoints
* deliberately unanswerable questions

Measure retrieval separately from generation. Track at minimum **Recall@k, MRR/nDCG,
context precision, context recall, answer faithfulness, citation correctness, latency,
and index/storage cost**. Use promptfoo or Inspect so the dataset feeds directly into
Project 3. Keep RAGAS-style answer/context metrics where useful, but do not let
LLM-as-judge scores replace deterministic retrieval metrics.

Publish an ablation table in the README:

| Configuration | Recall@10 | MRR/nDCG | Context Precision | Faithfulness | p95 latency | Index size |
|---|---:|---:|---:|---:|---:|---:|
| Lexical only | | | | | | |
| Dense only | | | | | | |
| Hybrid + RRF | | | | | | |
| + contextual headers | | | | | | |
| + reranker | | | | | | |
| + parent expansion | | | | | | |
| ColBERT / late interaction | | | | | | |

### 6. Security review — retrieval is a trust boundary

Treat every retrieval component as attacker-influenced and make each risk a runnable
test (OWASP LLM08:2025 Vector & Embedding Weaknesses plus agentic threat paths):

* **Poisoned-document indirect injection** — malicious instructions in an ebook are
  retrieved into model context; test both detection and downstream behavior.
* **Cross-user/collection leakage** — two principals, private collections, adversarial
  queries against the shared store; authorization must be enforced before ranking.
* **Metadata poisoning** — attacker-controlled title/author/chapter/context headers
  manipulate retrieval or citations.
* **Context flooding / retrieval DoS** — documents engineered to dominate candidate
  sets or consume excessive context/tokens.
* **Reranker manipulation** — adversarial passages score highly after initial retrieval.
* **Citation spoofing** — retrieved text attempts to make the model attribute evidence
  to the wrong book/chapter/page.
* **Embedding/vector leakage** — demonstrate or document inversion/reconstruction risk
  against your own vectors and define the storage/access boundary.
* **Write-path access control** — only explicitly authorized ingestion identities may
  mutate corpus/index state; map this to scoped credentials and audit logs.
* **Agentic search-loop abuse** — seed the Project-2 tests for queries/content that
  cause repeated searches, excessive context expansion, or resource exhaustion.

### 7. Prepare retrieval as an agent tool

Do **not** build the full agent loop yet. Define a narrow API/tool contract that Month
2 can expose through MCP, with operations such as:

```
search_library(query, filters, top_k)
read_passage(passage_id)
read_section(section_id)
read_chapter(chapter_id)
search_metadata(author, title, topic)
```

Return structured provenance with every result. Keep search/read separate so the
future agent can retrieve a small candidate set and deliberately request broader
context rather than receiving an uncontrolled context dump. Define authorization,
maximum results/context size, timeouts, and audit fields now.

**Explicitly defer to Project 2:** iterative query decomposition, multi-hop research,
agent-controlled repeated search, GraphRAG/knowledge-graph traversal, and autonomous
decisions about whether enough evidence has been gathered. GraphRAG is optional and
should be added only if the ebook eval set demonstrates relationship/multi-hop queries
that hybrid + hierarchical retrieval handles poorly.

## Week 4 — Study sprint

OWASP LLM Top 10 2025 + Agentic Top 10 2026 + ATLAS, applied: write Project 1's
threat model and design notes for Month 2 using their vocabulary.

Deliverables:

* ✅ Hardened `project-1` (k8s fully; Compose scoped per the k8s-first
  decision) + published threat model
* `retrieval-context-lab/` with a structural ebook corpus pipeline, retrieval API,
  benchmark/ablation results, and security tests in the README
* Design doc for the Secure Agent Platform

---

# Month 2

# Secure Agent Platform + Red Team Harness

**This is the differentiator project.** Anyone can wire up an agent in 2026;
almost no one can show sandboxed execution, scoped agent identity, and a
threat model on a real cluster.

## Project 2 — Secure Agent Platform

Repository: `secure-agent-platform`

Architecture:

```
User / Task
    ↓
Agent runtime (Claude Agent SDK, OpenAI Agents SDK, or Pydantic AI — pick one)
    ↓ MCP
MCP servers (your own: k8s read-only, Wazuh query, runbook search)
    ↓
Sandboxed execution (gVisor / Kata on Talos)   ← untrusted code paths
    ↓
LiteLLM gateway (existing) → models
```

### Build

* **Write 2–3 MCP servers** wrapping your own infrastructure: a read-only
  Kubernetes inspector, a Wazuh alert query tool, a documentation/runbook
  search backed by the Month-1 retrieval/context service. Real tools, real credentials,
  real consequences — which is what makes the hardening meaningful.
* An agent loop that uses them for a genuine task (e.g., "why is this pod
  crashlooping?"). For research/runbook tasks, implement **agentic retrieval**: the
  agent may search, inspect provenance, read a parent section/chapter, reformulate or
  decompose the query, search again, and stop only when it has sufficient evidence.
  Bound search iterations, context growth, and tool-call budgets.

### Harden (the actual point)

* **MCP threat model & hardening**: tool poisoning, retrieval/context poisoning,
  agentic search-loop abuse, SSRF from tool parameters
  (36%+ of public MCP servers were found potentially SSRF-vulnerable), confused
  deputy, tool-description injection, registry/supply-chain poisoning
  (study the ClawHub incident). Validate inputs, pin tool versions, authenticate
  the transport.
* **Sandboxing**: run agent code-execution and untrusted tool workloads under
  **gVisor or Kata Containers** on Talos (RuntimeClass). Document the isolation
  boundary and what escapes it would take. This is the skill AI companies build
  in-house and cannot hire for.
* **Agent identity & least privilege**: per-agent ServiceAccounts, **SPIFFE/SPIRE
  or native workload identity** for tool authentication, short-lived scoped
  credentials from Vault, OAuth token exchange where applicable. No agent holds
  a god token.
* **Human approval gates** for irreversible actions (anything that writes,
  deletes, or spends) — implement the pattern, not just the principle.
* **Kill switch & audit**: every tool call logged with agent identity, input,
  output; a way to revoke an agent's credentials instantly.

Map every control to an ASI01–ASI10 category in the threat model.

## Project 3 — AI Red Team & Eval Harness

Repository: `ai-redteam-harness`

* Learn and run **garak**, **PyRIT**, and **promptfoo** (red-team mode) against
  your own gateway and agents.
* Build a **prompt-injection regression suite**: a corpus of direct and indirect
  injection attacks (including injections embedded in retrieved documents and
  MCP tool outputs), executed in CI, reporting **attack success rate** per
  model/guardrail configuration.
* Measure before/after for each Project 2 mitigation — numbers, not vibes.
* Try **Inspect** (UK AISI) for structured evals.
* Sharpen intuition with public challenges: Gandalf, HackAPrompt-style CTFs.

Deliverables:

* `secure-agent-platform` — running on Talos, with threat model
* `ai-redteam-harness` — CI-integrated, with measured results
* Blog write-up #1: "Sandboxing AI agents on Talos with gVisor/Kata" (or the MCP hardening story)

---

# Month 3

# AI SecOps Platform + Model-Weight Security

## Project 4 — AI Security Operations Platform

Repository: `ai-secops-platform`

The original Month 3 project, **rebuilt on the Month 2 foundation** — the point
is no longer "an AI-powered SOC" (common in 2026) but "an agentic SOC built with
staff-level security architecture."

Architecture:

```
Wazuh · Kubernetes events · Trivy/Inspector · GitHub
    ↓
Investigation agents  (MCP tools from Project 2, sandboxed, scoped identity)
    ↓
LiteLLM gateway → models
    ↓
Findings: investigation reports · PRs · summaries   (behind approval gates)
```

Capabilities (unchanged from the original plan, now with secure plumbing):

* **Alert investigation**: Wazuh alert → root cause, impact, evidence, remediation
* **Kubernetes analysis**: "What changed in 24h?" / "Why is this deployment failing?" / "Which workloads violate policy?"
* **Vulnerability analysis**: CVE → summary, affected assets, severity, remediation
* **GitHub integration**: draft PRs and security reports — **write actions
  require human approval** (the ASI-informed design, demonstrated end-to-end)

Run the red-team harness against it: an attacker-controlled Wazuh alert or log
line is an **indirect prompt injection vector** into your investigation agent.
Show the attack, show the mitigation, measure it.

## Model-Weight & Infrastructure Security Track (study + lab, ~2 weeks parallel)

The AI-lab-specific material. Study the RAND SL1–SL5 framework, then implement
home-lab-scale versions of the controls:

* **Egress control**: treat Ollama's model files as protected weights; Cilium
  network policies + host firewall so the model server can serve inference but
  weights cannot leave (block/alert on bulk egress). Document the SL level this
  approximates and what SL4/SL5 would additionally require.
* **Attestation**: Talos supports TPM-based measured boot / disk encryption —
  enable and document it. Understand remote attestation and secure enclaves /
  confidential computing (incl. GPU TEE on H100-class hardware) at the concept
  level; know what you'd verify and when.
* **Two-party control**: require PR review + signed commits for changes to the
  AI namespaces in `k8s-gitops`; document as a two-person-integrity control.
* **Insider-risk framing**: write up how the lab maps to a lab-scale version of
  an AI company's weight-security program.

## Visibility (throughout Month 3)

* Blog write-up #2: threat-modeling an agentic SOC (or the weight-security lab)
* Contribute to the OWASP Agentic Security Initiative / GenAI project
* Responsible disclosure: audit a few public MCP servers with your harness; the
  ecosystem is target-rich and a CVE credit is a strong staff-level signal

Deliverables:

* `ai-secops-platform` with threat model + red-team results
* Weight-security lab documented in `docs/`
* Two published write-ups; one contribution or disclosure attempt

---

# Recommended Technologies (2026)

## Core platform (unchanged — still current)

* Python, FastAPI
* PostgreSQL + pgvector + PostgreSQL FTS, Redis
* BGE-M3-class embeddings + dedicated cross-encoder/BGE reranker serving
* ColBERT-style late interaction (experimental comparison, not mandatory production path)
* Open WebUI, LiteLLM, Ollama, vLLM
* ArgoCD, Helm

## Agentic (new)

* **MCP** — build and secure servers (primary skill)
* One agent SDK: **Claude Agent SDK**, OpenAI Agents SDK, or Pydantic AI
* **gVisor / Kata Containers** — sandboxing (RuntimeClass on Talos)
* **SPIFFE/SPIRE** — workload/agent identity

## Security testing (new)

* **garak**, **PyRIT**, **promptfoo** — automated red-teaming
* **Inspect** (UK AISI) — evals
* ModelScan / Fickling, **safetensors** — model artifact security

## Security (updated)

* Vault + ESO/VSO, Kyverno, Falco, Wazuh, Trivy, Cosign
* Sigstore **model signing** (OpenSSF), CycloneDX **AI/ML-BOM**
* Cilium NetworkPolicies (egress control)

## GPU / inference (updated)

* NVIDIA Device Plugin → **Dynamic Resource Allocation (DRA)** — the modern K8s GPU path
* MIG / time-slicing, vLLM in production
* (Deprioritized: KServe; watch: llm-d, NVIDIA NIM)

---

# Optional Project

## AI Radio Net Logger

Unchanged — still unique, still a great story:

SDR → Whisper → speaker ID → LLM → net summary
(check-in tracking, traffic logging, daily reports, incident summaries)

If built, apply the house style: sandbox the pipeline, threat-model the
untrusted input (RF audio is attacker-controlled input to an LLM — indirect
injection via transcript).

---

# Success Criteria

At the end of 90 days, you should be able to:

* Deploy and **harden** AI workloads on Kubernetes (policies, network, supply chain)
* **Build and threat-model MCP servers and agentic systems** (ASI01–ASI10 fluency)
* **Sandbox untrusted agent execution** with gVisor/Kata and explain the isolation boundary
* Design **agent identity and least-privilege tool access** (SPIFFE, scoped credentials, approval gates)
* **Red-team AI systems** with garak/PyRIT/promptfoo and run evals as CI regression gates
* Discuss **model-weight security** (RAND SLs, egress, attestation, confidential computing) the way AI labs do
* Operate model gateways with governance (keys, budgets, audit, guardrails)
* Design and benchmark **modern retrieval/context systems**: lexical + dense hybrid
  retrieval, RRF, reranking, contextual indexing, hierarchical parent expansion,
  late-interaction experiments, provenance, and retrieval-layer security
* Point to **published threat models, write-ups, and contributions** — not just repos
* Interview successfully for Security Engineering roles **at AI companies**, and for AI Infrastructure/Security roles elsewhere

The goal is not to compete with ML researchers.

The goal is to be the staff engineer who can securely run **agentic AI** in
production — and who understands what it takes to protect the models themselves.
