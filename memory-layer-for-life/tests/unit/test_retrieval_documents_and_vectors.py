"""What a memory is embedded as, and how vectors cross the wire."""

import math

import pytest

from app.db.vector import format_vector, parse_vector
from app.services.retrieval.documents import (
    DOCUMENT_VERSION,
    MAX_DOCUMENT_CHARS,
    document_sha256,
    memory_document,
    memory_type_label,
)

# --- Documents -------------------------------------------------------------------------


def test_a_document_names_the_kind_the_content_and_the_linked_entities() -> None:
    document = memory_document(
        "semantic_fact", "The user's  sister Priya\nlives in Pune.", ["Pune", "Priya"]
    )

    assert document == "Fact: The user's sister Priya lives in Pune.\nAbout: Priya, Pune"


def test_entity_names_are_deduplicated_and_sorted_without_case() -> None:
    document = memory_document("task", "Call them", ["netra", "Arjun", "Netra ", "", "netra"])

    assert document.endswith("About: Arjun, Netra, netra")


def test_a_memory_without_entities_has_no_about_line() -> None:
    assert memory_document("task", "Buy almonds", []) == "Task: Buy almonds"


def test_an_unknown_type_still_reads_as_words() -> None:
    assert memory_type_label("travel_plan") == "Travel plan"
    assert memory_document("travel_plan", "Goa", []) == "Travel plan: Goa"


def test_a_document_is_capped() -> None:
    assert len(memory_document("note", "word " * 5000, [])) == MAX_DOCUMENT_CHARS


def test_the_hash_is_of_the_exact_text() -> None:
    assert document_sha256("Task: Buy almonds") == document_sha256("Task: Buy almonds")
    assert document_sha256("Task: Buy almonds") != document_sha256("Task: Buy almonds.")
    assert len(document_sha256("x")) == 64


def test_the_document_version_is_recorded() -> None:
    # Bump it whenever memory_document changes what it writes.
    assert DOCUMENT_VERSION == "1"


# --- Vectors on the wire ---------------------------------------------------------------


def test_vectors_round_trip_through_their_text_form() -> None:
    values = [0.25, -1.0, 3.5e-7]

    assert parse_vector(format_vector(values)) == pytest.approx(values)
    assert format_vector([1, 2]) == "[1.0,2.0]"


@pytest.mark.parametrize("values", [[], [1.0, math.nan], [math.inf]])
def test_vectors_pgvector_would_reject_are_refused_early(values: list[float]) -> None:
    with pytest.raises(ValueError):
        format_vector(values)


def test_an_empty_text_vector_parses_as_empty() -> None:
    assert parse_vector("[]") == []
