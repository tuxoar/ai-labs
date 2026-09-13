"""EPUB -> structured chapters. Structure-aware prep is OUR code (the
downstream chunker gets real chapter boundaries, not one flat blob)."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from markdownify import markdownify


@dataclass
class Chapter:
    title: str
    seq: int
    markdown: str


@dataclass
class Book:
    title: str
    author: str | None
    source_hash: str
    chapters: list[Chapter]


_WS = re.compile(r"\n{3,}")


def _chapter_title(soup: BeautifulSoup, fallback: str) -> str:
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)[:200]
    return fallback


def parse_epub(path: Path, min_chars: int = 200) -> Book:
    """Split on spine documents (the author's own chapter boundaries).
    Items shorter than min_chars (covers, nav, colophons) are dropped."""
    raw = path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    book = epub.read_epub(str(path), options={"ignore_ncx": True})

    def meta(field: str) -> str | None:
        values = book.get_metadata("DC", field)
        return values[0][0] if values else None

    chapters: list[Chapter] = []
    seq = 0
    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for junk in soup(["script", "style", "nav"]):
            junk.decompose()
        md = markdownify(str(soup.body or soup), heading_style="ATX", strip=["img", "a"])
        md = _WS.sub("\n\n", md).strip()
        if len(md) < min_chars:
            continue
        seq += 1
        chapters.append(Chapter(title=_chapter_title(soup, f"Section {seq}"), seq=seq, markdown=md))

    return Book(
        title=meta("title") or path.stem,
        author=meta("creator"),
        source_hash=source_hash,
        chapters=chapters,
    )
