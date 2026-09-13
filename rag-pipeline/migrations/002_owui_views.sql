-- Views shaped for Open WebUI's external pgvector provider (v0.11.0 defaults:
-- fields id / collection_name / text / vector / vmetadata). One view per
-- embedder so the provider's single vector_field maps cleanly; the connection
-- config points table_name at rag.owui_nomic (or owui_bgem3).
-- The vmetadata keys feed citation display (source/name) plus filters.

CREATE OR REPLACE VIEW rag.owui_nomic AS
SELECT
    c.id::text        AS id,
    c.collection_name AS collection_name,
    c.text            AS text,
    c.emb_nomic       AS vector,
    jsonb_build_object(
        'source',  b.title,
        'name',    coalesce(c.chapter, b.title),
        'book',    b.title,
        'author',  b.author,
        'chapter', c.chapter,
        'seq',     c.seq
    )                 AS vmetadata
FROM rag.chunks c
JOIN rag.books  b ON b.id = c.book_id
WHERE c.emb_nomic IS NOT NULL;

CREATE OR REPLACE VIEW rag.owui_bgem3 AS
SELECT
    c.id::text        AS id,
    c.collection_name AS collection_name,
    c.text            AS text,
    c.emb_bgem3       AS vector,
    jsonb_build_object(
        'source',  b.title,
        'name',    coalesce(c.chapter, b.title),
        'book',    b.title,
        'author',  b.author,
        'chapter', c.chapter,
        'seq',     c.seq
    )                 AS vmetadata
FROM rag.chunks c
JOIN rag.books  b ON b.id = c.book_id
WHERE c.emb_bgem3 IS NOT NULL;
