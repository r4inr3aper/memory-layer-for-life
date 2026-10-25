"""Written reports are served from the project, and only the ones that are listed."""

from pathlib import Path

import pytest

from app.domain.errors import RecordNotFoundError
from app.services.reports import REPORTS, ReportService


def test_a_listed_report_is_read_with_its_title_and_modification_time(tmp_path: Path) -> None:
    (tmp_path / REPORTS["phase-1"].file_name).write_text("# Phase 1\n\nDone.\n", encoding="utf-8")

    document = ReportService(tmp_path).get("phase-1")

    assert document.slug == "phase-1"
    assert document.title == "Phase 1 report"
    assert document.markdown == "# Phase 1\n\nDone.\n"
    assert document.updated_at.tzinfo is not None


def test_a_listed_report_whose_file_is_missing_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(RecordNotFoundError):
        ReportService(tmp_path).get("phase-1")


def test_an_unlisted_slug_is_not_found_even_when_a_file_exists(tmp_path: Path) -> None:
    """Only listed files can be served: a slug is never turned into a path."""
    (tmp_path / "secret.md").write_text("no", encoding="utf-8")

    with pytest.raises(RecordNotFoundError):
        ReportService(tmp_path).get("secret")
    with pytest.raises(RecordNotFoundError):
        ReportService(tmp_path).get("../secret")
