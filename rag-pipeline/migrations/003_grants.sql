-- Grants for the two pipeline roles (created by apply-migrations.sh, which
-- owns the passwords — roles cannot be parameterized in plain SQL files).
--   rag_ingest : the ingestion pipeline (write path)
--   rag_read   : Open WebUI external knowledge connection + rag-api (read-only)
-- Demonstrates write-path access control at the DB layer (threat model LLM08).

GRANT CONNECT ON DATABASE knowledge TO rag_ingest;
GRANT CONNECT ON DATABASE knowledge TO rag_read;

GRANT USAGE ON SCHEMA rag TO rag_ingest;
GRANT USAGE ON SCHEMA rag TO rag_read;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rag TO rag_ingest;
GRANT SELECT ON ALL TABLES IN SCHEMA rag TO rag_read;

ALTER DEFAULT PRIVILEGES IN SCHEMA rag GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO rag_ingest;
ALTER DEFAULT PRIVILEGES IN SCHEMA rag GRANT SELECT ON TABLES TO rag_read;
