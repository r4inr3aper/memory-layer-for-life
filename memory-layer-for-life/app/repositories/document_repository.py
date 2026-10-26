import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Float, cast, delete, func, literal_column, select, update

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_file import DocumentFile
from app.repositories.base import BaseRepository

# Matches are marked in a snippet with these, as in chat search.
_HIGHLIGHT = "StartSel=<<, StopSel=>>, MaxWords=60, MinWords=25, MaxFragments=2"


class DocumentRepository(BaseRepository):
    """Persistence of the user's documents and their passages. Every lookup is scoped to
    the owner, so another user's document reads as missing."""

    async def add(self, document: Document, chunks: Sequence[DocumentChunk]) -> Document:
        self._session.add(document)
        await self._session.flush()
        self._session.add_all(chunks)
        await self._session.flush()
        return document

    async def add_file(self, document: Document, file: DocumentFile) -> None:
        """Keep a document's original file (ADR-050)."""
        self._session.add(file)
        document.has_file = True
        await self._session.flush()

    async def file_data(self, document_id: uuid.UUID) -> bytes | None:
        """A document's original file, or None when only its text was kept."""
        result: bytes | None = await self._session.scalar(
            select(DocumentFile.data).where(DocumentFile.document_id == document_id)
        )
        return result

    async def stored_bytes(self, user_id: uuid.UUID) -> int:
        """How much the user's kept files take together."""
        total = await self._session.scalar(
            select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                Document.user_id == user_id, Document.has_file.is_(True)
            )
        )
        return int(total or 0)

    async def get(
        self, user_id: uuid.UUID, document_id: uuid.UUID, *, for_update: bool = False
    ) -> Document | None:
        statement = select(Document).where(Document.id == document_id, Document.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        result: Document | None = await self._session.scalar(statement)
        return result

    async def by_hash(self, user_id: uuid.UUID, file_sha256: str) -> Document | None:
        result: Document | None = await self._session.scalar(
            select(Document).where(Document.user_id == user_id, Document.file_sha256 == file_sha256)
        )
        return result

    async def resume(self, user_id: uuid.UUID) -> Document | None:
        result: Document | None = await self._session.scalar(
            select(Document).where(Document.user_id == user_id, Document.is_resume.is_(True))
        )
        return result

    async def list_for(self, user_id: uuid.UUID) -> list[Document]:
        """The user's documents, the resume first, then most recently changed."""
        rows = await self._session.scalars(
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.is_resume.desc(), Document.updated_at.desc(), Document.id)
        )
        return list(rows)

    async def unmark_resume(self, user_id: uuid.UUID, *, except_id: uuid.UUID | None) -> None:
        """No document of the user is their resume any more, except ``except_id``."""
        conditions = [Document.user_id == user_id, Document.is_resume.is_(True)]
        if except_id is not None:
            conditions.append(Document.id != except_id)
        await self._session.execute(
            update(Document)
            .where(*conditions)
            .values(is_resume=False)
            .execution_options(synchronize_session=False)
        )

    async def delete(self, document: Document) -> None:
        """Delete a document. Its passages and its file go with it, by the foreign keys'
        cascade."""
        await self._session.execute(delete(Document).where(Document.id == document.id))

    async def chunks(
        self, document_id: uuid.UUID, *, limit: int | None = None
    ) -> list[DocumentChunk]:
        """A document's passages in reading order."""
        statement = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal)
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(await self._session.scalars(statement))

    async def search(
        self, user_id: uuid.UUID, tsquery_source: str, *, limit: int
    ) -> list[tuple[DocumentChunk, Document, str]]:
        """The user's passages matching any of the query's terms (``any_term_tsquery``),
        best first, each with its document and a highlighted snippet."""
        english: ColumnElement[str] = literal_column("'english'::regconfig")
        simple: ColumnElement[str] = literal_column("'simple'::regconfig")
        tsquery = func.to_tsquery(english, tsquery_source).op("||")(
            func.to_tsquery(simple, tsquery_source)
        )
        rank = cast(func.ts_rank_cd(DocumentChunk.search_document, tsquery, 32), Float)
        snippet = func.ts_headline(english, DocumentChunk.content, tsquery, _HIGHLIGHT)
        rows = await self._session.execute(
            select(DocumentChunk, Document, snippet)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.user_id == user_id,
                DocumentChunk.search_document.op("@@")(tsquery),
            )
            .order_by(rank.desc(), Document.updated_at.desc(), DocumentChunk.ordinal)
            .limit(limit)
        )
        return [(row[0], row[1], str(row[2])) for row in rows]
