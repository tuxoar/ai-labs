"""Chunking strategies. Paragraph-respecting fixed-size splitter with overlap;
chapters are never merged across boundaries (structure-aware by construction).
The optional contextual header — "<Book> — <Chapter>" prepended to every
chunk — is ablation (a) in the eval matrix."""

import hashlib
from dataclasses import dataclass

from .parse import Book, Chapter


@dataclass
class Chunk:
    chapter: str
    seq: int          # global sequence within the book/variant
    text: str
    content_hash: str
    meta: dict


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


def chunk_book(
    book: Book,
    collection: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
    contextual_headers: bool = False,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq = 0
    for ch in book.chapters:
        for piece in _pack(_split_paragraphs(ch.markdown), chunk_size, chunk_overlap):
            seq += 1
            text = piece
            if contextual_headers:
                text = f"[{book.title} — {ch.title}]\n{piece}"
            chunks.append(
                Chunk(
                    chapter=ch.title,
                    seq=seq,
                    text=text,
                    content_hash=hashlib.sha256(f"{collection}\x00{text}".encode()).hexdigest(),
                    meta={"chapter_seq": ch.seq},
                )
            )
    return chunks
