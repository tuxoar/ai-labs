"""Parser/chunker hierarchy — no EPUB fixtures needed (the corpus is private);
synthetic markdown exercises the same code paths."""

from pipeline.chunk import chunk_book
from pipeline.parse import Book, Chapter, split_sections


def _md(n_paras: int, prefix: str) -> str:
    return "\n\n".join(f"{prefix} paragraph {i} " + "lorem ipsum " * 20 for i in range(n_paras))


def test_split_sections_builds_preamble_h2_h3():
    md = "# Chapter One\n\n" + _md(3, "intro") + "\n\n## Alpha\n\n" + _md(4, "alpha") \
         + "\n\n### Alpha detail\n\n" + _md(4, "detail") + "\n\n## Beta\n\n" + _md(3, "beta")
    secs = split_sections("Chapter One", md, min_chars=100)
    assert [s.heading for s in secs] == ["Chapter One", "Alpha", "Alpha detail", "Beta"]
    assert [s.depth for s in secs] == [1, 2, 3, 2]
    assert [s.seq for s in secs] == [1, 2, 3, 4]
    assert all(s.markdown.strip() for s in secs)


def test_split_sections_merges_runts_and_falls_back():
    md = "## Big\n\n" + _md(5, "big") + "\n\n## Tiny\n\nshort.\n\n## Next\n\n" + _md(5, "next")
    secs = split_sections("Ch", md, min_chars=400)
    # "Tiny" merges into "Big" (predecessor), "Next" stands alone.
    assert [s.heading for s in secs] == ["Big", "Next"]
    assert "short." in secs[0].markdown

    plain = split_sections("Ch", _md(4, "plain"))
    assert len(plain) == 1 and plain[0].heading is None and plain[0].depth == 0


def _book() -> Book:
    chapters = []
    for cseq in (1, 2):
        md = "# Ch%d\n\n" % cseq + _md(2, "pre") + "\n\n## S1\n\n" + _md(6, "s1") + "\n\n## S2\n\n" + _md(6, "s2")
        title = f"Ch{cseq}"
        chapters.append(Chapter(title=title, seq=cseq, markdown=md, sections=split_sections(title, md, 100)))
    return Book(title="Test Book", author="Ann Author", source_hash="x" * 64, chapters=chapters)


def test_chapter_split_is_phase1_compatible():
    """split='chapter' must produce the exact Phase-1 text (hash-stable for
    the three live collections): header is '[Book — Chapter]' and no
    section ids are assigned."""
    chunks = chunk_book(_book(), "col", chunk_size=800, chunk_overlap=100, contextual_headers=True)
    assert chunks[0].text.startswith("[Test Book — Ch1]\n")
    assert all(c.section_seq is None for c in chunks)
    assert all(c.meta == {"chapter_seq": c.chapter_seq} for c in chunks)
    assert [c.seq for c in chunks] == list(range(1, len(chunks) + 1))


def test_section_split_never_crosses_headings():
    book = _book()
    chunks = chunk_book(book, "col-h", chunk_size=800, chunk_overlap=100, split="section",
                        contextual_headers=True)
    assert all(c.section_seq is not None for c in chunks)
    for c in chunks:
        body = c.text.split("\n", 1)[1]
        assert body.count("## ") <= 1          # at most its own heading
        if c.section_seq == 2:
            assert c.text.startswith("[Test Book — Ch1 — S1]\n") or c.text.startswith("[Test Book — Ch2 — S1]\n")
    # Preamble header does not repeat the chapter title.
    pre = [c for c in chunks if c.section_seq == 1][0]
    assert pre.text.startswith("[Test Book — Ch1]\n")
    # Distinct hashes per collection.
    other = chunk_book(book, "col-h2", chunk_size=800, chunk_overlap=100, split="section")
    assert {c.content_hash for c in chunks}.isdisjoint({c.content_hash for c in other})
