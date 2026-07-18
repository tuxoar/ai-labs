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
4. Compresses the RAG Knowledge Platform from a month to ~1–2 weeks (it's a tutorial in 2026, not a differentiator).
5. Rebuilds the AI SecOps project on the secure-agent foundation, with a published threat model.
6. Updates all study material to OWASP LLM Top 10 (2025), Agentic Top 10 (2026), MITRE ATLAS, and NIST AI RMF.
7. Adds a **visibility layer**: published threat models and write-ups, OSS contributions, responsible disclosure.

---

# Target Portfolio

At the end of 90 days, the portfolio should contain:

1. **Basic AI Platform on Kubernetes** — ✅ built (Compose + Helm/Talos); hardening pass remains
2. **Secure Agent Platform** — MCP servers, sandboxed execution, agent identity *(the differentiator)*
3. **AI Red Team & Eval Harness** — automated injection/jailbreak testing wired into CI
4. **AI Security Operations Platform** — investigation agents built on the secure foundation
5. **Model-Weight Security Lab** — egress controls, attestation, RAND SL mapping *(spans month 3)*
6. AI Knowledge Platform — compressed RAG exercise *(1–2 weeks, folded into Month 1)*
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

## Changes to apply to Project 1 (hardening pass, ~1 week)

These upgrades convert the platform from "deployed" to "defensible," and each one
is a portfolio talking point. Roughly in priority order:

### Governance (finish the existing roadmap items)

* **Per-user LiteLLM virtual keys + budgets** — stop using the master key from
  Open WebUI; issue scoped keys with spend limits and TPM/RPM rate limits. This is
  the foundation for every later cost/abuse control.
* **Model allow-lists per key** — demonstrate least-privilege at the gateway.

### Network security (plays directly to Cilium/Talos strengths)

* **Kubernetes NetworkPolicies** for the `basic-ai-platform` namespace:
  default-deny; Postgres/Redis reachable only from LiteLLM and Open WebUI;
  **egress allowed only to `ai-server:11434`** and DNS. The egress rule matters
  most — it is the first concrete instance of the egress-control theme in the
  Month 3 weight-security track.
* Firewall/documented exposure for the unauthenticated exporters on `ai-server`
  (`:9100`, `:9400`) if not already done.

### Policy & supply chain

* **Kyverno policies** on the namespace: require image digests (not tags),
  disallow privileged/root, require resource limits, restrict registries.
* **Sign and verify**: pin the six images by digest; verify signatures where
  upstream signs (or re-sign into your own registry with Cosign) and enforce
  with Kyverno `verifyImages`. Generate SBOMs with Trivy in CI.

### Gateway as security control point

* **LiteLLM guardrail hooks**: enable prompt-injection detection / content
  filtering callbacks on the gateway so every model call passes a control point.
  Even a simple heuristic + logging hook demonstrates the architecture.
* **Structured audit logging** of prompts/responses/user/model to Postgres
  (already partially there via LiteLLM logs) — document retention and access.

### Testing

* Extend `smoke-test.sh` into a **CI job** (GitHub Actions) that runs `helm template`
  + `kubeconform`, Trivy scans, and — once the Month 2 eval harness exists — a
  prompt-injection regression suite against the gateway.

### Documentation

* Add a **threat model** (`docs/threat-model.md`) using the OWASP LLM Top 10 2025
  categories: trust boundaries, the "Ollama has no auth" gateway rationale,
  what's mitigated vs. accepted. This becomes the template for every later project.

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

# Harden the Foundation + RAG Fundamentals

## Week 1 — Project 1 hardening pass

Execute the "Changes to apply to Project 1" list above.

## Weeks 2–3 — Compressed RAG exercise (formerly the Month 2 project)

Build a minimal ebook RAG pipeline into the existing pgvector instance:
ingestion → chunking → embeddings (`embed-nomic` / `embed-bge-m3` already
exposed) → retrieval in Open WebUI with citations. Timebox it — this teaches
fundamentals, it is not a differentiator.

**Keep the modern part:** a small **eval set** (25–50 questions measuring
retrieval and citation accuracy) and a **vector-store security** review —
access control on retrieval, embedding inversion risk, cross-user data leakage
via shared collections (now an OWASP category: Vector & Embedding Weaknesses).

Skip: knowledge graphs, collections taxonomy, MOBI/AZW handling, polish.

## Week 4 — Study sprint

OWASP LLM Top 10 2025 + Agentic Top 10 2026 + ATLAS, applied: write Project 1's
threat model and design notes for Month 2 using their vocabulary.

Deliverables:

* Hardened `project-1` (both variants) + threat model
* `rag-exercise/` with eval results in the README
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
  search. Real tools, real credentials, real consequences — which is what makes
  the hardening meaningful.
* An agent loop that uses them for a genuine task (e.g., "why is this pod
  crashlooping?").

### Harden (the actual point)

* **MCP threat model & hardening**: tool poisoning, SSRF from tool parameters
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
* PostgreSQL + pgvector, Redis
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
* Build RAG systems and secure the vector layer
* Point to **published threat models, write-ups, and contributions** — not just repos
* Interview successfully for Security Engineering roles **at AI companies**, and for AI Infrastructure/Security roles elsewhere

The goal is not to compete with ML researchers.

The goal is to be the staff engineer who can securely run **agentic AI** in
production — and who understands what it takes to protect the models themselves.
