import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UpdateTimestampMixin, UUIDMixin
from app.db.constraints import enum_check
from app.domain.enums import LinkKind


class SavedLink(Base, UUIDMixin, UpdateTimestampMixin):
    """A link the user saved for the assistant to share for them, such as their resume on
    Google Drive or their portfolio (ADR-050).

    Shared as it is: nothing is fetched from it. The same address twice is the same link.
    At most one link per user is their resume, enforced by a partial unique index.
    """

    __tablename__ = "saved_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        CheckConstraint(enum_check("kind", LinkKind), name="valid_kind"),
        CheckConstraint("length(title) > 0", name="non_empty_title"),
        CheckConstraint("length(url) > 0", name="non_empty_url"),
        UniqueConstraint("user_id", "url"),
        Index("ix_saved_links_user_id_updated_at", "user_id", "updated_at"),
        Index(
            "uq_saved_links_one_resume_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'resume'"),
        ),
    )
