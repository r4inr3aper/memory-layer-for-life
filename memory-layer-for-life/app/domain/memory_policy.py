"""What the pipeline does with a memory it built (ADR-048), and how memories are labelled.

* Accepted on its own, when it is sure: confident, not sensitive, the user's own words,
  and not a memory the user already has. Everything else waits in To review, which then
  holds the exceptions only, not every memory.
* The same memory said again is not saved twice: the new evidence goes to the memory the
  user already has. The model words a memory differently every time, so the comparison
  is on meaning anchors (a shared link) and text similarity, never on exact words. Money
  notes are never merged: two notes of "103 auto" can be two rides.
* Lists show a short title: the extractor's, or the content with its evidence-style
  phrasing ("Task as written: ...") trimmed.

None of it needs a database or a model. Bump ``AUTO_ACCEPT_RULE`` whenever the rule
changes: the memory's history records which rule accepted it.
"""

import re
from collections.abc import Mapping
from typing import Any, Final

from app.domain.enums import ExtractionDisposition, MemoryType, MessageSource

AUTO_ACCEPT_RULE: Final = "auto-accept/1"
AUTO_ACCEPT_MIN_CONFIDENCE: Final = 0.8

# Similarity (pg_trgm, 0 to 1) above which two memories of one kind are the same memory.
DUPLICATE_SIMILARITY: Final = 0.8
# Enough when both point at the same link: "Look at the post at <url> and mail it" and
# "Review the post at <url> and mail it" are one task.
ANCHORED_SIMILARITY: Final = 0.45
# Kinds whose repeats are separate facts: two equal amounts can be two expenses.
NEVER_MERGED: Final = frozenset({MemoryType.FINANCIAL_NOTE})

# Sources whose text is the user's own words throughout. A WhatsApp import mixes speakers,
# so only its "Me:" lines are.
_OWN_WORDS_SOURCES: Final = frozenset(
    {
        MessageSource.APP_CHAT,
        MessageSource.FILE_UPLOAD,
        MessageSource.MANUAL_CAPTURE,
        MessageSource.API_INPUT,
    }
)
_OWN_LINE: Final = re.compile(r"^\s*me\s*:", re.IGNORECASE)

TITLE_MAX_CHARS: Final = 80
_URL: Final = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_URL_TRAILING: Final = ".,;:!?"
# Evidence-style phrasing the extractor uses to stay faithful, which a list does not need.
_TITLE_PREFIX: Final = re.compile(
    r"^(?:task|reminder|note|question|open question|unclear note)(?:\s+as written)?\s*:\s*",
    re.IGNORECASE,
)
_AS_WRITTEN: Final = re.compile(
    r"\s*\((?:as written|as written in the note)\)|,?\s+as written(?: in the note)?\b",
    re.IGNORECASE,
)
# Straight, curly, and back quotes.
_QUOTES: Final = "\"'`\u201c\u201d\u2018\u2019"


def is_own_words(source: MessageSource, content: str) -> bool:
    """Whether a message is the user speaking, rather than someone they chat with."""
    if source in _OWN_WORDS_SOURCES:
        return True
    return source is MessageSource.WHATSAPP_IMPORT and bool(_OWN_LINE.match(content))


def auto_accept(
    *,
    confidence: float,
    sensitive: bool,
    disposition: ExtractionDisposition,
    own_words: bool,
) -> bool:
    """Whether a memory can be accepted without the user looking at it.

    Sensitive memories always wait: the user decides what private matters are kept.
    Other people's words always wait: they are evidence, not facts about the user.
    """
    return (
        disposition is not ExtractionDisposition.ABSTAIN
        and own_words
        and not sensitive
        and confidence >= AUTO_ACCEPT_MIN_CONFIDENCE
    )


def urls_in(text: str) -> frozenset[str]:
    """The links in a text, without trailing punctuation, compared case-insensitively."""
    return frozenset(match.rstrip(_URL_TRAILING).lower() for match in _URL.findall(text))


def is_duplicate(
    memory_type: MemoryType,
    *,
    similarity: float,
    shares_link: bool,
) -> bool:
    """Whether a new memory of ``memory_type`` is one the user already has, given how alike
    the two texts are and whether both point at the same link."""
    if memory_type in NEVER_MERGED:
        return False
    if shares_link:
        return similarity >= ANCHORED_SIMILARITY
    return similarity >= DUPLICATE_SIMILARITY


def clean_title(text: str, *, max_chars: int = TITLE_MAX_CHARS) -> str:
    """One line, no surrounding quotes or final full stop, cut at a word boundary."""
    line = " ".join(text.split()).strip(_QUOTES + " ")
    line = line.rstrip(".").strip()
    if len(line) > max_chars:
        cut = line[: max_chars - 1].rsplit(" ", 1)[0] or line[: max_chars - 1]
        line = f"{cut.rstrip(',;:')}…"
    return line[:1].upper() + line[1:]


def display_title(content: str, metadata: Mapping[str, Any]) -> str:
    """What a list shows for a memory: the extractor's title when it wrote one, otherwise
    the content without evidence-style phrasing."""
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return clean_title(title)
    text = _AS_WRITTEN.sub("", content)
    text = _TITLE_PREFIX.sub("", text.strip())
    return clean_title(text) or clean_title(content)
