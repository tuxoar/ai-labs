-- Phase 3: the document hierarchy  book -> chapter -> section -> passage.
-- Parent text is stored ONCE per level (not duplicated into every chunk) so
-- retrieval can find a passage and expand upward: "retrieve narrowly, read
-- broadly". Additive and nullable: collections ingested before this migration
-- keep working; `rag ingest` backfills chapter_id for them from
-- meta->>'chapter_seq', and section_id is populated for section-split
-- collections (manifest: split: section).

CREATE TABLE IF NOT EXISTS rag.chapters (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id       uuid NOT NULL REFERENCES rag.books(id) ON DELETE CASCADE,
    seq           int  NOT NULL,                 -- spine order after junk filtering
    title         text NOT NULL,
    text_md       text NOT NULL,                 -- normalized chapter markdown
    content_hash  text NOT NULL,                 -- sha256(text_md): re-parse detection
    meta          jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (book_id, seq)
);

CREATE TABLE IF NOT EXISTS rag.sections (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id    uuid NOT NULL REFERENCES rag.chapters(id) ON DELETE CASCADE,
    seq           int  NOT NULL,                 -- order within the chapter
    heading       text,                          -- NULL = whole-chapter fallback
    depth         int  NOT NULL DEFAULT 0,       -- 0 fallback, 1 preamble, 2 h2, 3 h3
    text_md       text NOT NULL,
    content_hash  text NOT NULL,
    meta          jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (chapter_id, seq)
);

ALTER TABLE rag.chunks ADD COLUMN IF NOT EXISTS chapter_id uuid REFERENCES rag.chapters(id) ON DELETE SET NULL;
ALTER TABLE rag.chunks ADD COLUMN IF NOT EXISTS section_id uuid REFERENCES rag.sections(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS chapters_book_idx    ON rag.chapters (book_id);
CREATE INDEX IF NOT EXISTS sections_chapter_idx ON rag.sections (chapter_id);
CREATE INDEX IF NOT EXISTS chunks_chapter_idx   ON rag.chunks (chapter_id);
CREATE INDEX IF NOT EXISTS chunks_section_idx   ON rag.chunks (section_id);

-- Catalog search (search_metadata tool): chapter titles + section headings.
CREATE INDEX IF NOT EXISTS chapters_title_tsv_gin ON rag.chapters USING gin (to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS sections_heading_tsv_gin ON rag.sections USING gin (to_tsvector('english', coalesce(heading, '')));

-- 003's ALTER DEFAULT PRIVILEGES already covers tables created by the
-- migration role; explicit grants keep this file self-contained.
GRANT SELECT, INSERT, UPDATE, DELETE ON rag.chapters, rag.sections TO rag_ingest;
GRANT SELECT ON rag.chapters, rag.sections TO rag_read;

-- Open WebUI views: deepen citations with the section heading and a stable
-- passage id now that parents exist (same column shape, so CREATE OR REPLACE).
CREATE OR REPLACE VIEW rag.owui_nomic AS
SELECT
    c.id::text        AS id,
    c.collection_name AS collection_name,
    c.text            AS text,
    c.emb_nomic       AS vector,
    jsonb_build_object(
        'source',     b.title,
        'name',       coalesce(s.heading, c.chapter, b.title),
        'book',       b.title,
        'author',     b.author,
        'chapter',    c.chapter,
        'section',    s.heading,
        'seq',        c.seq,
        'passage_id', c.id::text,
        'section_id', c.section_id::text,
        'chapter_id', c.chapter_id::text
    )                 AS vmetadata
FROM rag.chunks c
JOIN rag.books  b ON b.id = c.book_id
LEFT JOIN rag.sections s ON s.id = c.section_id
WHERE c.emb_nomic IS NOT NULL;

CREATE OR REPLACE VIEW rag.owui_bgem3 AS
SELECT
    c.id::text        AS id,
    c.collection_name AS collection_name,
    c.text            AS text,
    c.emb_bgem3       AS vector,
    jsonb_build_object(
        'source',     b.title,
        'name',       coalesce(s.heading, c.chapter, b.title),
        'book',       b.title,
        'author',     b.author,
        'chapter',    c.chapter,
        'section',    s.heading,
        'seq',        c.seq,
        'passage_id', c.id::text,
        'section_id', c.section_id::text,
        'chapter_id', c.chapter_id::text
    )                 AS vmetadata
FROM rag.chunks c
JOIN rag.books  b ON b.id = c.book_id
LEFT JOIN rag.sections s ON s.id = c.section_id
WHERE c.emb_bgem3 IS NOT NULL;
