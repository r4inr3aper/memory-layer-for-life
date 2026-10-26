"""Documents the user uploads for the assistant to read (ADR-049): which files are taken,
how their text is cleaned and cut into passages, and when one is a resume. No database,
no model.

A document is reference material, kept whole. It is not turned into memories: a resume
becomes "knows Python" fragments that way, which is useless for writing an application,
and deleting the file would leave the fragments behind.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Final

from app.domain.memory_policy import clean_title

PDF: Final = "application/pdf"
DOCX: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PLAIN_TEXT: Final = "text/plain"
MARKDOWN: Final = "text/markdown"
DOCUMENT_TYPES: Final = frozenset({PDF, DOCX, PLAIN_TEXT, MARKDOWN})

# Passages are about this long: a paragraph or a few, enough to answer from.
PASSAGE_CHARS: Final = 1500
TITLE_MAX_CHARS: Final = 120
# A PDF page with less text than this on average has no usable text layer: a scan.
MIN_CHARS_PER_PAGE: Final = 40

_RESUME_NAME: Final = re.compile(r"(?<![a-z])(resume|résumé|cv|curriculum)(?![a-z])", re.I)
_RESUME_SECTIONS: Final = (
    "experience",
    "education",
    "skills",
    "projects",
    "work history",
    "employment",
    "certifications",
)
_BLANK_LINES: Final = re.compile(r"\n{3,}")
_TRAILING_SPACE: Final = re.compile(r"[ \t]+\n")


@dataclass(frozen=True, slots=True)
class Passage:
    ordinal: int
    # The page it starts on (1-based), when the document has pages.
    page: int | None
    content: str


def title_from_file_name(file_name: str) -> str:
    """A readable title from a file name: no extension, no underscores."""
    stem = PurePath(file_name).stem or file_name
    words = re.sub(r"[_]+", " ", stem)
    return clean_title(words, max_chars=TITLE_MAX_CHARS) or "Document"


def clean_text(text: str) -> str:
    """Text fit to store: no NUL characters (PostgreSQL refuses them), Unix line ends, no
    trailing spaces, at most one blank line in a row."""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def looks_like_resume(file_name: str, text: str) -> bool:
    """Whether a document is most likely the user's resume: it says so in its name, or it
    has the sections a resume has."""
    if _RESUME_NAME.search(file_name):
        return True
    head = text[:6000].lower()
    return sum(1 for section in _RESUME_SECTIONS if section in head) >= 3


def passages(pages: Sequence[str], *, target_chars: int = PASSAGE_CHARS) -> list[Passage]:
    """Cut a document's pages into passages of about ``target_chars``, along paragraphs,
    in reading order. A paragraph longer than that is cut at word boundaries."""
    paged = len(pages) > 1
    result: list[Passage] = []
    current: list[str] = []
    current_page: int | None = None
    size = 0

    def flush() -> None:
        nonlocal current, size, current_page
        if current:
            result.append(Passage(len(result), current_page, "\n\n".join(current)))
        current, size, current_page = [], 0, None

    for number, page in enumerate(pages, start=1):
        for paragraph in (part.strip() for part in page.split("\n\n")):
            if not paragraph:
                continue
            for piece in _pieces(paragraph, target_chars):
                if size and size + len(piece) > target_chars:
                    flush()
                if current_page is None:
                    current_page = number if paged else None
                current.append(piece)
                size += len(piece) + 2
    flush()
    return result


def _pieces(paragraph: str, limit: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]
    pieces = []
    rest = paragraph
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit)
        cut = cut if cut > limit // 2 else limit
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces
