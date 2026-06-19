-- Runs once on first cluster init (empty data dir). Creates the per-service
-- databases and enables pgvector. The default POSTGRES_DB from .env already
-- exists; we add dedicated DBs for LiteLLM, Open WebUI, and the knowledge base.

CREATE DATABASE litellm;
CREATE DATABASE openwebui;
CREATE DATABASE knowledge;

-- pgvector lives in the knowledge DB (used by Project 2 RAG ingestion).
\connect knowledge
CREATE EXTENSION IF NOT EXISTS vector;
