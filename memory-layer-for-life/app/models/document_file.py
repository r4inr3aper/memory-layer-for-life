import uuid

from sqlalchemy import ForeignKey, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DocumentFile(Base, TimestampMixin):
    """The original file of a document, kept so the assistant can attach it to an app
    action, such as a resume to a job application email (ADR-050).

    A row of its own so listing and reading documents never loads the bytes. Deleted with
    its document. Documents uploaded before revision 016 have none (``has_file`` false):
    only their text was kept.
    """

    __tablename__ = "document_files"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
