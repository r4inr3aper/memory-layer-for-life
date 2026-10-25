"""Written project reports, served to the console as Markdown.

A report is a Markdown file kept in the project. The console shows it next to live
figures, so the written account and the data it describes are read together. Only the
files named here can be served.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from app.domain.errors import RecordNotFoundError


@dataclass(frozen=True, slots=True)
class ReportFile:
    title: str
    file_name: str


REPORTS: Final[dict[str, ReportFile]] = {
    "phase-1": ReportFile(title="Phase 1 report", file_name="PHASE1_REPORT.md"),
}


@dataclass(frozen=True, slots=True)
class ReportDocument:
    slug: str
    title: str
    markdown: str
    updated_at: datetime


class ReportService:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get(self, slug: str) -> ReportDocument:
        """Read a report. Raises ``RecordNotFoundError`` for an unknown or missing one."""
        report = REPORTS.get(slug)
        if report is None:
            raise RecordNotFoundError("Report", slug)
        path = self._root / report.file_name
        try:
            markdown = path.read_text(encoding="utf-8")
            modified = path.stat().st_mtime
        except FileNotFoundError as error:
            raise RecordNotFoundError("Report", slug) from error
        return ReportDocument(
            slug=slug,
            title=report.title,
            markdown=markdown,
            updated_at=datetime.fromtimestamp(modified, tz=UTC),
        )
