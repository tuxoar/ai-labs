"""EPUB -> structured book: chapters (spine documents) -> sections (heading
tree) -> markdown. Structure-aware prep is OUR code: the chunker gets real
chapter AND section boundaries, and parents are kept for expansion."""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from markdownify import markdownify


@dataclass
class Section:
    seq: int            # order within the chapter (1-based)
    heading: str | None  # None = whole-chapter fallback
    depth: int          # 0 fallback, 1 preamble (before first heading), 2 h2, 3 h3
    markdown: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.markdown.encode()).hexdigest()


@dataclass
class Chapter:
    title: str
    seq: int
    markdown: str
    sections: list[Section] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.markdown.encode()).hexdigest()


@dataclass
class Book:
    title: str
    author: str | None
    source_hash: str
    chapters: list[Chapter]


_WS = re.compile(r"\n{3,}")
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _chapter_title(soup: BeautifulSoup, fallback: str) -> str:
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)[:200]
    return fallback


def split_sections(chapter_title: str, md: str, min_chars: int = 400) -> list[Section]:
    """Split chapter markdown on ATX h2/h3 headings. Text before the first
    heading is the preamble (depth 1, titled after the chapter). Sections
    shorter than min_chars are merged into their predecessor so a lone
    heading never becomes its own retrieval unit. No headings -> one
    depth-0 section covering the chapter."""
    matches = list(_HEADING.finditer(md))
    if not matches:
        return [Section(seq=1, heading=None, depth=0, markdown=md)]

    pieces: list[tuple[str | None, int, str]] = []
    pre = md[: matches[0].start()].strip()
    if pre:
        pieces.append((chapter_title, 1, pre))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[m.start() : end].strip()
        pieces.append((m.group(2).strip()[:200], len(m.group(1)), body))

    # A runt (shorter than min_chars) folds into its predecessor; a runt that
    # opens the chapter absorbs its successor instead (keeps its heading).
    merged: list[tuple[str | None, int, str]] = []
    for heading, depth, body in pieces:
        if merged and (len(body) < min_chars or len(merged[-1][2]) < min_chars):
            h, d, prev = merged[-1]
            merged[-1] = (h, d, prev + "\n\n" + body)
        else:
            merged.append((heading, depth, body))

    return [Section(seq=i + 1, heading=h, depth=d, markdown=b) for i, (h, d, b) in enumerate(merged)]


def parse_epub(path: Path, min_chars: int = 200, min_section_chars: int = 400) -> Book:
    """Split on spine documents (the author's own chapter boundaries), then on
    headings within each. Items shorter than min_chars (covers, nav,
    colophons) are dropped."""
    raw = path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    book = epub.read_epub(str(path), options={"ignore_ncx": True})

    def meta(field_name: str) -> str | None:
        values = book.get_metadata("DC", field_name)
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
        title = _chapter_title(soup, f"Section {seq}")
        chapters.append(
            Chapter(title=title, seq=seq, markdown=md, sections=split_sections(title, md, min_section_chars))
        )

    return Book(
        title=meta("title") or path.stem,
        author=meta("creator"),
        source_hash=source_hash,
        chapters=chapters,
    )
