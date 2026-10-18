"""Chunking strategies. Paragraph-respecting fixed-size packing with overlap
inside a structural unit — a chapter (split="chapter", the Phase-1 behaviour,
hash-stable for existing collections) or a section (split="section", Phase 3:
overlap never crosses a heading and every chunk knows its section). The
optional contextual header — "[Book — Chapter — Section]" prepended to every
chunk — is ablation row "+ contextual headers" in the eval matrix."""

import hashlib
from dataclasses import dataclass

from .parse import Book, Chapter, Section


@dataclass
class Chunk:
    chapter: str
    seq: int          # global sequence within the book/variant
    text: str
    content_hash: str
    meta: dict
    chapter_seq: int = 0
    section_seq: int | None = None   # None for chapter-split chunks


def _split_paragraphs(md: str) -> list[str]:
    return [p.strip() for p in md.split("\n\n") if p.strip()]


def _pack(paragraphs: list[str], size: int, overlap: int) -> list[str]:
    """Greedy paragraph packing to ~size chars; overlap carries the tail
    paragraphs of the previous chunk forward. Oversized single paragraphs are
    hard-split (rare in prose)."""
    out: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for p in paragraphs:
        while len(p) > size:          # pathological paragraph
            out.append(p[:size])
            p = p[max(size - overlap, 1):]
        if buf_len + len(p) > size and buf:
            out.append("\n\n".join(buf))
            # overlap: keep trailing paragraphs up to `overlap` chars
            tail: list[str] = []
            tlen = 0
            for q in reversed(buf):
                if tlen + len(q) > overlap:
                    break
                tail.insert(0, q)
                tlen += len(q)
            buf, buf_len = tail, tlen
        buf.append(p)
        buf_len += len(p)
    if buf:
        out.append("\n\n".join(buf))
    return out


def _header(book: Book, ch: Chapter, sec: Section | None) -> str:
    parts = [book.title, ch.title]
    if sec is not None and sec.heading and sec.heading != ch.title:
        parts.append(sec.heading)
    return "[" + " — ".join(parts) + "]\n"


def chunk_book(
    book: Book,
    collection: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    contextual_headers: bool = False,
    split: str = "chapter",
) -> list[Chunk]:
    if split not in ("chapter", "section"):
        raise ValueError(f"split must be 'chapter' or 'section', got {split!r}")
    chunks: list[Chunk] = []
    seq = 0

    def emit(ch: Chapter, sec: Section | None, piece: str) -> None:
        nonlocal seq
        seq += 1
        text = (_header(book, ch, sec) + piece) if contextual_headers else piece
        meta = {"chapter_seq": ch.seq}
        if sec is not None:
            meta["section_seq"] = sec.seq
            meta["section_depth"] = sec.depth
        chunks.append(
            Chunk(
                chapter=ch.title,
                seq=seq,
                text=text,
                content_hash=hashlib.sha256(f"{collection}\x00{text}".encode()).hexdigest(),
                meta=meta,
                chapter_seq=ch.seq,
                section_seq=sec.seq if sec is not None else None,
            )
        )

    for ch in book.chapters:
        if split == "chapter":
            for piece in _pack(_split_paragraphs(ch.markdown), chunk_size, chunk_overlap):
                emit(ch, None, piece)
        else:
            for sec in ch.sections:
                for piece in _pack(_split_paragraphs(sec.markdown), chunk_size, chunk_overlap):
                    emit(ch, sec, piece)
    return chunks
