"""The text a memory is embedded and reranked as.

A memory's content alone can lose what its links know: "She moved to Pune" does not say
who "she" is, but the memory's entity links do. The document therefore states the kind of
memory, its content, and the people, places, and things it is linked to.

The exact text decides an embedding's validity: every stored embedding keeps the hash of
the text it was made from and the ``DOCUMENT_VERSION`` of this builder. Changing what goes
into a document is a new version, and the indexer re-embeds exactly the memories whose
document changed.
"""

import hashlib
from collections.abc import Iterable
from typing import Final

DOCUMENT_VERSION: Final = "1"
# Far above any memory; a guard against an unusual one costing a large embedding call.
MAX_DOCUMENT_CHARS: Final = 4000

_TYPE_LABELS: Final = {
    "semantic_fact": "Fact",
    "episodic_event": "Event",
    "preference": "Preference",
    "intention": "Intention",
    "task": "Task",
    "commitment": "Commitment",
    "goal": "Goal",
    "project": "Project",
    "decision": "Decision",
    "idea": "Idea",
    "open_loop": "Open question",
    "plan": "Plan",
    "note": "Note",
    "reflection": "Reflection",
    "resource": "Resource",
    "financial_note": "Money",
}


def memory_type_label(memory_type: str) -> str:
    return _TYPE_LABELS.get(memory_type) or memory_type.replace("_", " ").capitalize()


def memory_document(memory_type: str, content: str, entity_names: Iterable[str]) -> str:
    """``Fact: The user's sister Priya lives in Pune.`` then ``About: Priya, Pune``."""
    # Ties between spellings of one name are broken by the spelling itself, so the document
    # (and its hash) never depends on set iteration order.
    names = sorted(
        {name.strip() for name in entity_names if name.strip()},
        key=lambda name: (name.casefold(), name),
    )
    lines = [f"{memory_type_label(memory_type)}: {' '.join(content.split())}"]
    if names:
        lines.append(f"About: {', '.join(names)}")
    return "\n".join(lines)[:MAX_DOCUMENT_CHARS]


def document_sha256(document: str) -> str:
    return hashlib.sha256(document.encode("utf-8")).hexdigest()
