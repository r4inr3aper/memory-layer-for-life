"""Reading a document's text without a model (ADR-049).

* PDF: the text layer, page by page, with pypdf, in the order the PDF draws it, which for
  resumes exported from Word or Google Docs is column by column. A PDF without one (a
  scan) is reported as having no text, so the caller can decide whether a model may read
  it.
* Word (.docx): a zip whose ``word/document.xml`` holds the paragraphs; read with the
  standard library, with limits against zip and XML bombs.
* Plain text and Markdown: decoded as UTF-8.

Pure CPU work: callers run it in a thread.
"""

import io
import zipfile
from dataclasses import dataclass
from typing import Final
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.documents import (
    DOCX,
    MARKDOWN,
    MIN_CHARS_PER_PAGE,
    PDF,
    PLAIN_TEXT,
    clean_text,
)
from app.domain.enums import DocumentExtraction
from app.domain.errors import InvalidDocumentError

# The largest uncompressed document.xml read from a .docx.
_MAX_DOCX_XML_BYTES: Final = 30 * 1024 * 1024
_MAX_PDF_PAGES: Final = 300
_WORD: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass(frozen=True, slots=True)
class DocumentText:
    # The text of each page; one entry for formats without pages. Cleaned.
    pages: tuple[str, ...]
    extraction: DocumentExtraction
    page_count: int | None

    @property
    def chars(self) -> int:
        return sum(len(page) for page in self.pages)


def read_document_text(data: bytes, media_type: str) -> DocumentText:
    """The document's text. A PDF without a text layer comes back with no text; anything
    unreadable raises ``InvalidDocumentError`` with a message for the user."""
    if media_type == PDF:
        return _read_pdf(data)
    if media_type == DOCX:
        return _read_docx(data)
    if media_type in (PLAIN_TEXT, MARKDOWN):
        text = clean_text(data.decode("utf-8", errors="replace"))
        return DocumentText((text,), DocumentExtraction.PLAIN_TEXT, None)
    raise InvalidDocumentError("Upload a PDF, a Word document (.docx), or a text file.")


def has_text_layer(text: DocumentText) -> bool:
    """Whether a PDF's text layer holds real text, rather than nothing or stray marks."""
    pages = max(text.page_count or len(text.pages), 1)
    return text.chars >= MIN_CHARS_PER_PAGE * pages * 0.5


def _read_pdf(data: bytes) -> DocumentText:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise InvalidDocumentError(
                "This PDF is password-protected. Remove the password and upload it again."
            )
        count = len(reader.pages)
        if count > _MAX_PDF_PAGES:
            raise InvalidDocumentError(
                f"This PDF has {count} pages. Upload one of at most {_MAX_PDF_PAGES}."
            )
        pages = tuple(clean_text(page.extract_text() or "") for page in reader.pages)
    except InvalidDocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise InvalidDocumentError("This PDF could not be opened. It may be damaged.") from error
    return DocumentText(pages, DocumentExtraction.TEXT_LAYER, count)


def _read_docx(data: bytes) -> DocumentText:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_DOCX_XML_BYTES:
                raise InvalidDocumentError("This Word document is too large to read.")
            xml = archive.read(info)
        root = ElementTree.fromstring(xml)
    except InvalidDocumentError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as error:
        raise InvalidDocumentError(
            "This Word document could not be opened. Save it as .docx and try again."
        ) from error

    paragraphs = []
    for paragraph in root.iter(f"{_WORD}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{_WORD}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_WORD}tab":
                parts.append("\t")
            elif node.tag in (f"{_WORD}br", f"{_WORD}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    text = clean_text("\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip()))
    return DocumentText((text,), DocumentExtraction.DOCX, None)
