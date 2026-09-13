-- rag schema: owned by the pipeline, consumed read-only by Open WebUI's
-- external knowledge connection and (Phase 3) rag-api.
-- Applied to the `knowledge` DB (pgvector extension already created there by
-- the platform's 01-init.sql). Idempotent.

CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE IF NOT EXISTS rag.books (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title        text NOT NULL,
    author       text,
    source_hash  text NOT NULL UNIQUE,          -- sha256 of the EPUB file (idempotency)
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    meta         jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- One row per chunk per collection. A "collection" encodes an ingestion
-- variant (chunking strategy etc.); re-chunking = new collection, never a
-- migration. Embeddings are per-model columns: simple HNSW indexing and a
-- clean field mapping for Open WebUI's external pgvector provider. The
-- >2000-dim escape hatch (halfvec or an embeddings side-table) is documented
-- in the README before it is ever needed.
CREATE TABLE IF NOT EXISTS rag.chunks (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_name text NOT NULL,
    book_id         uuid NOT NULL REFERENCES rag.books(id) ON DELETE CASCADE,
    chapter         text,
    seq             int  NOT NULL,
    text            text NOT NULL,
    content_hash    text NOT NULL,              -- sha256(collection ⊕ text)
    meta            jsonb NOT NULL DEFAULT '{}'::jsonb,
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    emb_nomic       vector(768),
    emb_bgem3       vector(1024),
    UNIQUE (collection_name, content_hash)
);

CREATE INDEX IF NOT EXISTS chunks_collection_idx ON rag.chunks (collection_name);
CREATE INDEX IF NOT EXISTS chunks_book_idx       ON rag.chunks (book_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin        ON rag.chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_emb_nomic_hnsw ON rag.chunks
    USING hnsw (emb_nomic vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS chunks_emb_bgem3_hnsw ON rag.chunks
    USING hnsw (emb_bgem3 vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS rag.schema_migrations (
    filename   text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
