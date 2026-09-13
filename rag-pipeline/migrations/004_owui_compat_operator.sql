-- Compat shim for an UPSTREAM Open WebUI bug (v0.11.0,
-- retrieval/external.py::_retrieve_pgvector): the query embedding is bound as
-- a plain Python list -> double precision[], so its SQL
--     vector_column <=> %s
-- fails with "operator does not exist: vector <=> double precision[]".
-- This defines that operator via pgvector's array->vector cast. Created in
-- public so Open WebUI's unqualified <=> resolves through its default
-- search_path.
--
-- KNOWN LIMIT: the HNSW index is NOT used through this operator (it's not the
-- opclass operator) — Track A external retrieval seq-scans the collection.
-- Fine at 10^4..10^5 chunks; Track B (rag-api) binds typed vectors and uses
-- the index properly. File/track the upstream fix so this shim can die.

CREATE OR REPLACE FUNCTION public.vector_cosdist_f8array(vector, double precision[])
RETURNS double precision
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS 'SELECT $1 <=> $2::vector';

DO $$
BEGIN
    CREATE OPERATOR public.<=> (
        LEFTARG   = vector,
        RIGHTARG  = double precision[],
        FUNCTION  = public.vector_cosdist_f8array
    );
EXCEPTION WHEN duplicate_function THEN
    NULL;  -- operator already exists (re-run)
END $$;

GRANT EXECUTE ON FUNCTION public.vector_cosdist_f8array(vector, double precision[]) TO rag_read;
