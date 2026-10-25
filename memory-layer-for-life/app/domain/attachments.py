"""Files a user can attach to a chat message: the types the model reads directly."""

from typing import Final

IMAGE_TYPES: Final = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
DOCUMENT_TYPES: Final = frozenset({"application/pdf"})
ATTACHMENT_TYPES: Final = IMAGE_TYPES | DOCUMENT_TYPES
