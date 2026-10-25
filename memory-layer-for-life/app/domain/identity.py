"""Source and processing identities.

Three identities are kept apart on purpose:

* Source identity names the original incoming message: ``(source, source_message_id)``.
  It is enforced by a unique constraint and exists only when the source supplies an id.
* Processing identity names one logical run: an ordered unit of messages processed
  under one pipeline fingerprint. It is the ``idempotency_key`` of a processing run.
* Output identity names what a run produced. It is enforced by unique constraints on
  the extraction result and on each derived record's ordinal.

A content hash is a diagnostic value, never an identity: two messages with identical
text are still two messages.
"""

import hashlib
import uuid
from collections.abc import Sequence
from typing import Final

from app.domain.errors import InvalidProcessingUnitError
from app.domain.versions import PipelineFingerprint

# Prefix of every idempotency key. Change it only together with the key construction.
IDEMPOTENCY_KEY_SCHEME: Final = "v1"


def content_sha256(content: str) -> str:
    """Hex SHA-256 of the exact UTF-8 bytes of the content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def processing_idempotency_key(
    raw_message_ids: Sequence[uuid.UUID], fingerprint: PipelineFingerprint
) -> str:
    """Build the idempotency key of one logical processing operation.

    The key covers the ordered message ids and the pipeline fingerprint, so:

    * the same unit under the same configuration always maps to the same run;
    * a new configuration maps to a new run and leaves history untouched;
    * the same messages in a different order or grouping are a different unit.

    Message ids are database ids, not content hashes, so two distinct messages with the
    same text can never collapse into one key.
    """
    if not raw_message_ids:
        raise InvalidProcessingUnitError("A processing unit needs at least one message.")
    if len(set(raw_message_ids)) != len(raw_message_ids):
        raise InvalidProcessingUnitError("A processing unit cannot list a message twice.")

    material = "\n".join(
        [IDEMPOTENCY_KEY_SCHEME, fingerprint.digest(), *(str(i) for i in raw_message_ids)]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{IDEMPOTENCY_KEY_SCHEME}:{digest}"
