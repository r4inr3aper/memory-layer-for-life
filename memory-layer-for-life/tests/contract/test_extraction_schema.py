"""The extraction contract as the model sees it.

The JSON schema sent to the provider is pinned by a snapshot. A change to the contract
shows up here as a diff and must be deliberate: bump ``EXTRACTION_SCHEMA_VERSION`` and
``EXTRACTION_PROMPT_VERSION`` as needed, then regenerate the snapshot with::

    python -m tests.contract.test_extraction_schema
"""

import json
from pathlib import Path
from typing import Any

from anthropic import transform_schema

from app.domain.enums import (
    EntityType,
    ExtractionDisposition,
    MemoryState,
    MemoryType,
    Sensitivity,
)
from app.domain.versions import EXTRACTION_SCHEMA_VERSION
from app.schemas.extraction import ExtractionOutput, ExtractionPayload
from evaluation.judge import JudgeVerdict

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "extraction_output_schema.json"

# JSON Schema keywords the provider's structured outputs do not support.
UNSUPPORTED_KEYWORDS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "maxItems",
    "uniqueItems",
}
# The one array constraint the provider enforces: a minimum of zero or one item.
SUPPORTED_MIN_ITEMS = {0, 1}


def provider_schema() -> dict[str, Any]:
    return transform_schema(ExtractionOutput)


def walk(node: Any):  # type: ignore[no-untyped-def]
    """Yield every JSON object in a schema."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def test_schema_sent_to_the_provider_matches_the_snapshot() -> None:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert snapshot["schema_version"] == EXTRACTION_SCHEMA_VERSION
    assert provider_schema() == snapshot["schema"], (
        "The extraction contract changed. If that is intended, bump the schema version "
        "and regenerate the snapshot (see this module's docstring)."
    )


def test_every_object_is_closed_and_every_field_is_required() -> None:
    """Structured outputs need closed objects, and the model must state every field."""
    objects = [node for node in walk(provider_schema()) if node.get("type") == "object"]

    assert len(objects) >= 5
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])


def test_schema_uses_only_supported_keywords() -> None:
    for schema in (provider_schema(), transform_schema(JudgeVerdict)):
        nodes = list(walk(schema))
        used = {key for node in nodes for key in node if key in UNSUPPORTED_KEYWORDS}
        assert used == set()
        assert {node["minItems"] for node in nodes if "minItems" in node} <= SUPPORTED_MIN_ITEMS


def test_schema_exposes_the_controlled_vocabularies() -> None:
    definitions = provider_schema()["$defs"]

    assert definitions["MemoryType"]["enum"] == [item.value for item in MemoryType]
    assert definitions["MemoryState"]["enum"] == [item.value for item in MemoryState]
    assert definitions["Sensitivity"]["enum"] == [item.value for item in Sensitivity]
    assert definitions["EntityType"]["enum"] == [item.value for item in EntityType]
    assert definitions["ExtractionDisposition"]["enum"] == [
        item.value for item in ExtractionDisposition
    ]


def test_schema_never_asks_the_model_for_system_owned_facts() -> None:
    """Ids, timestamps, offsets, and normalized forms are computed, never requested."""
    property_names = {
        name for node in walk(provider_schema()) for name in node.get("properties", {})
    }

    assert not property_names & {
        "id",
        "raw_message_id",
        "extracted_at",
        "created_at",
        "start_offset",
        "end_offset",
        "normalized_mention",
        "schema_version",
        "status",
    }


def test_persisted_payload_wraps_the_output_with_its_version() -> None:
    assert set(ExtractionPayload.model_fields) == {
        "schema_version",
        "normalizer_version",
        "message_ids",
        "output",
    }


def write_snapshot() -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(
            {"schema_version": EXTRACTION_SCHEMA_VERSION, "schema": provider_schema()},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_snapshot()
    print(f"Wrote {SNAPSHOT_PATH}")
