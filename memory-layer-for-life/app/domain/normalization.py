"""Deterministic text normalization.

Raw message content is immutable evidence and is never changed. These functions build
working representations from it. Their behavior is versioned by
``app.domain.versions.NORMALIZER_VERSION``: change that version whenever a function
here would produce different output for the same input.
"""

import re
import unicodedata
from typing import Final

# Invisible format characters that carry no meaning for extraction, as code points so the
# source stays readable. Zero-width joiner (200D) and non-joiner (200C) are deliberately
# absent: they shape emoji sequences and several Indic scripts.
_REMOVED_CODE_POINTS: Final = (
    0x200B,  # zero-width space
    0x2060,  # word joiner
    0xFEFF,  # byte order mark
    0x200E,  # left-to-right mark
    0x200F,  # right-to-left mark
    0x202A,  # left-to-right embedding
    0x202B,  # right-to-left embedding
    0x202C,  # pop directional formatting
    0x202D,  # left-to-right override
    0x202E,  # right-to-left override
    0x2066,  # left-to-right isolate
    0x2067,  # right-to-left isolate
    0x2068,  # first strong isolate
    0x2069,  # pop directional isolate
)
_REMOVED_CHARACTERS: Final = frozenset(chr(code_point) for code_point in _REMOVED_CODE_POINTS)

# Curly single and double quotation marks.
_CURLY_QUOTES: Final = "".join(chr(code_point) for code_point in (0x2018, 0x2019, 0x201C, 0x201D))

# Punctuation stripped from the edges of an entity name. Symbols such as "+" and "#" are
# kept so that names like "C++" and "C#" survive.
_ENTITY_EDGE_PUNCTUATION: Final = "\"'`" + _CURLY_QUOTES + "()[]{}<>.,;:!?*_~"

_WHITESPACE_RUN: Final = re.compile(r"\s+")


def normalize_message_text(text: str) -> str:
    """Return the working form of a message that is handed to the extractor.

    The transformation is conservative: Unicode NFC, uniform line endings, invisible
    format characters removed, exotic space characters mapped to a plain space, trailing
    whitespace trimmed. Words, punctuation, digits, and line structure are preserved.
    """
    composed = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    characters: list[str] = []
    for character in composed:
        if character in _REMOVED_CHARACTERS:
            continue
        if character != " " and unicodedata.category(character) == "Zs":
            characters.append(" ")
            continue
        characters.append(character)
    lines = [line.rstrip() for line in "".join(characters).split("\n")]
    return "\n".join(lines).strip()


def normalize_for_matching(text: str) -> str:
    """Return a comparison key: compatibility-folded, case-folded, single-spaced."""
    folded = unicodedata.normalize("NFKC", normalize_message_text(text)).casefold()
    return _WHITESPACE_RUN.sub(" ", folded).strip()


def normalize_entity_name(name: str) -> str:
    """Return the key used to compare entity names.

    Equal keys mean the names are written the same way. They do not prove that two
    mentions refer to the same real-world entity; that decision belongs to resolution.
    """
    return normalize_for_matching(name).strip(_ENTITY_EDGE_PUNCTUATION).strip()


def contains_quote(text: str, quote: str) -> bool:
    """Tell whether ``quote`` occurs in ``text``, ignoring case and spacing differences."""
    needle = normalize_for_matching(quote)
    return bool(needle) and needle in normalize_for_matching(text)


def locate_span(text: str, fragment: str) -> tuple[int, int] | None:
    """Find the first occurrence of ``fragment`` in ``text``.

    Returns ``(start, end)`` character offsets into ``text``, or ``None`` when the
    fragment does not occur verbatim (case differences are tolerated). Offsets are only
    reported when they can be verified, so they are never guessed.
    """
    if not fragment:
        return None
    start = text.find(fragment)
    if start >= 0:
        return start, start + len(fragment)
    match = re.search(re.escape(fragment), text, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.start(), match.end()
