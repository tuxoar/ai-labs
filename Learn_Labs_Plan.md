# AI Infrastructure & Security Engineering Learning Plan

## 90-Day Intensive Portfolio Program

### Goal

The goal of these labs is to strengthen skills towards being an: 

* AI Infrastructure Engineer
* AI Platform Engineer
* AI Security Engineer
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

The objective is not to become a data scientist, instead is to become the engineer who can securely deploy, operate, govern, and scale AI systems.

---

# Target Portfolio

At the end of 90 days, the portfolio should contain:

1. Secure AI Platform on Kubernetes
2. Enterprise AI Control Plane
3. AI Knowledge Platform
4. AI Security Operations Platform
5. AI Radio Net Logger (Optional)

---

# Existing Environment

## Infrastructure

### Talos Kubernetes Cluster

* GitOps managed
* Existing ArgoCD workflows
* Existing observability stack
* Existing security tooling

### Local AI Server

Current purpose:

* Local model serving
* Llama models
* Coding models
* Inference endpoint

Treat this server as:

* Internal model provider
* Local Bedrock equivalent

Do not immediately move model serving into Kubernetes.

The Kubernetes cluster should consume AI services from the local AI server.

---

# Month 1

# Build an AI Platform Foundation

## Objectives

Learn:

* LLM fundamentals
* Model serving
* AI gateways
* Vector databases
* RAG fundamentals
* AI observability

---

## Project 1

### Secure AI Platform

Deploy:

* Open WebUI
* LiteLLM
* PostgreSQL
* pgvector
* Redis
* Prometheus
* Grafana

Architecture:

Users
↓
Open WebUI
↓
LiteLLM
↓
Local AI Model Server

---

## Skills

### AI Fundamentals

Learn:

* Tokens
* Context windows
* Embeddings
* RAG
* Fine tuning
* Tool calling
* Prompt injection

---

### Model Serving

Learn:

* Ollama
* vLLM
* LiteLLM

Understand:

* OpenAI compatible APIs
* Model routing
* Context handling
* Streaming responses

---

### Vector Search

Learn:

* pgvector
* Embeddings
* Similarity search
* Hybrid search

---

## Deliverables

Git repository:

talos-ai-platform

Must include:

* GitOps deployment
* Monitoring
* Documentation
* Architecture diagrams

---

## pgvector Sub-Projects

Optional, self-contained tasks to exercise pgvector within Project 1, before the full RAG build in Project 2.

Each uses:

* pgvector (knowledge DB)
* Embedding models via LiteLLM (embed-nomic 768, embed-bge-m3 1024, embed-arctic2 1024)
* A small Python service (uv)
* Embedding calls routed through the gateway (visible in Grafana)

---

### 1. Embedding Model Benchmark

Goal:

Compare the three embedding models on the same corpus.

Build:

* Separate vector(768) / vector(1024) tables per model
* A query set with expected results
* Recall@k measurement

Learn:

* Cosine distance (<=>)
* Why dimension count and index choice matter

Bridges to: Project 2 (model selection for RAG)

---

### 2. CVE Semantic Search

Goal:

Natural-language search over real security data.

Build:

* Ingest a slice of the NVD CVE feed (public JSON)
* Embed each description into pgvector
* Query: "container escape via runtime", "kubelet privilege escalation"

Learn:

* HNSW index
* Cosine distance
* Metadata filtering (CVSS, year)

Bridges to: Project 3 (alert / CVE investigation)

---

### 3. Prompt-Injection Detector

Goal:

Embedding-similarity guardrail for the gateway.

Build:

* Corpus of known jailbreak / injection prompts
* Embed and store in pgvector
* Score incoming prompts by similarity to nearest known-bad
* Flag / block above a threshold

Learn:

* Nearest-neighbor scoring
* OWASP LLM01 (Prompt Injection)
* LiteLLM guardrail callbacks (turn it into a real gateway control)

Bridges to: Project 4 (governance / security controls)

---

### 4. Semantic Response Cache

Goal:

Cache semantically similar prompts, not just identical ones.

Build:

* Embed each prompt, store with its response
* On new prompt, return cached answer if a near-match exists
* Tunable similarity threshold + TTL

Learn:

* Similarity thresholds
* Trade-offs vs exact-match (Redis) caching

Bridges to: gateway efficiency / cost control

---

### 5. pgvector Index Performance Lab

Goal:

Understand vector index behavior at scale.

Build:

* Load N synthetic/real vectors
* Compare HNSW vs IVFFlat (latency, recall, build time)
* Expose query latency as a Grafana panel

Learn:

* Index types and tuning
* EXPLAIN / ANALYZE for vector queries
* Capacity planning

Bridges to: platform performance engineering

---

# Month 2

# AI Knowledge Platform

## Objectives

Create a private AI-powered knowledge system using the ebook collection.

This project demonstrates:

* RAG
* Knowledge engineering
* Search
* Vector databases
* AI platform design

---

## Project 2

### AI Knowledge Platform

Architecture:

Ebooks
↓
Ingestion Pipeline
↓
Metadata Extraction
↓
Chunking
↓
Embeddings
↓
pgvector
↓
Open WebUI
↓
LLM

---

## Supported Formats

* PDF
* EPUB
* MOBI
* AZW (where legally usable)

---

## Metadata

Extract:

* Title
* Author
* ISBN
* Categories
* Publication Year
* Chapter Structure

---

## Features

### Semantic Search

Examples:

"Find books discussing Kubernetes admission control."

"Find all references to AI governance."

"Compare authors discussing platform security."

---

### Citation Grounding

Responses must provide:

* Book
* Chapter
* Page
* Section

---

### Collections

Create collections:

#### Security

* AppSec
* Cloud Security
* Kubernetes Security
* Incident Response

#### Infrastructure

* Kubernetes
* Linux
* Networking
* Platform Engineering

#### AI

* LLMs
* ML Systems
* AI Infrastructure
* AI Security

#### Radio

* Amateur Radio
* SDR
* Emergency Communications

---

## Advanced Features

### Knowledge Graph

Build relationships:

Book
↓
Concept
↓
Related Concepts

Example:

Kubernetes
↔ Admission Control
↔ OPA
↔ Kyverno
↔ Security

---

### Evaluation Suite

Create:

50-100 questions

Measure:

* Retrieval accuracy
* Citation accuracy
* Hallucination rate

---

## Deliverables

Git repository:

ai-knowledge-platform

---

# Month 3

# AI Security Platform

## Objectives

Combine:

* Security Engineering
* AI
* Kubernetes
* Wazuh

into a unified platform.

---

## Project 3

### AI Security Operations Platform

Architecture:

Wazuh
Inspector
Kubernetes
GitHub
↓
Agent Layer
↓
LLM
↓
Investigation Reports

---

## Capabilities

### Alert Investigation

Input:

Wazuh Alert

Output:

* Root Cause
* Impact
* Evidence
* Remediation

---

### Kubernetes Analysis

Questions:

"What changed in the last 24 hours?"

"Why is this deployment failing?"

"Which containers violate policy?"

---

### Vulnerability Analysis

Input:

CVE

Output:

* Summary
* Affected Assets
* Severity
* Remediation

---

### GitHub Integration

Generate:

* Pull Requests
* Security Reports
* Findings Summaries

---

## Deliverables

Git repository:

ai-secops-platform

---

# Enterprise AI Governance Layer

This becomes the differentiator.

---

## Project 4

### Enterprise AI Control Plane

Architecture:

Users
↓
Gateway
↓
Claude
GPT
Bedrock
Llama
DeepSeek

---

## Governance Features

### Model Allow Lists

Only approved models may be used.

---

### Cost Controls

Track:

* Tokens
* Requests
* Usage

---

### Audit Logging

Capture:

* Prompts
* Responses
* Users
* Model Selection

---

### Security Controls

Detect:

* Prompt Injection
* Data Exfiltration
* Excessive Tool Usage

---

## Deliverables

Git repository:

enterprise-ai-control-plane

---

# AI Security Engineering Topics

Master these subjects.

---

## OWASP LLM Top 10

Study:

* Prompt Injection
* Data Leakage
* Excessive Agency
* Model Theft
* Supply Chain Risks

---

## Model Supply Chain Security

Learn:

* Cosign
* Sigstore
* SBOMs
* Provenance

Implement:

* Signed images
* Verified deployments

---

## Runtime Security

Implement:

* Falco
* Wazuh
* Network Policies
* Workload Identity

---

## AI Secrets Management

Implement:

* Vault
* ESO
* VSO

Use dynamic credentials where possible.

---

# GPU Infrastructure Learning

## Topics

Learn:

* NVIDIA Device Plugin
* MIG
* GPU Sharing
* GPU Scheduling
* KServe
* Ray Serve
* vLLM

---

## Future Architecture

Talos Cluster

Control Plane Nodes
↓
Standard Workers
↓
GPU Workers

Use:

nvidia.com/gpu resources

for workload scheduling.

---

# Recommended Technologies

## Core

* Python
* FastAPI
* PostgreSQL
* pgvector
* Redis
* Open WebUI
* LiteLLM
* Ollama
* vLLM
* ArgoCD

---

## Security

* Vault
* Kyverno
* Falco
* Wazuh
* Trivy
* Cosign

---

## AI

* LlamaIndex
* LangGraph
* OpenAI APIs
* Embeddings

---

# Optional Project

## AI Radio Net Logger

Architecture:

SDR
↓
Whisper
↓
Speaker Identification
↓
LLM
↓
Net Summary

Capabilities:

* Check-in tracking
* Traffic logging
* Daily reports
* Incident summaries

This project is highly unique and can significantly differentiate a portfolio.

---

# Success Criteria

At the end of 90 days, you should be able to:

* Deploy AI workloads on Kubernetes
* Secure AI platforms
* Implement AI governance
* Build RAG systems
* Operate model gateways
* Monitor AI workloads
* Secure model supply chains
* Design enterprise AI architectures
* Discuss AI infrastructure at a staff engineer level
* Interview successfully for AI Infrastructure and AI Security Engineering roles

The goal is not to compete with ML researchers.

The goal is to become the engineer who can securely run AI in production at scale.

