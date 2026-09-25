"""R8.23 — `text-csv` converts a CSV file to its text as written.

A markdown table was the obvious alternative and was rejected (spec 008, "An HTML
page or a CSV file someone exported"): it rewrites every row, so a model quoting
the table would quote text the file does not hold. A person reading a CSV sees
its cells, and so does a model reading its text.

`PLAY-4004` is `tests/fixtures/documents/exports/PLAY-4004-incident-register.csv`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.infrastructure.converters.text_csv import TextCsvConverter

REGISTER = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "exports"
    / "PLAY-4004-incident-register.csv"
)


class TestACsvFileConvertsToItsText:
    """R8.23 — the register's text is its note."""

    def test_the_artifact_is_the_files_text(self):
        """Example 1: the one where `PLAY-4004` is converted."""
        payload = REGISTER.read_bytes()

        written = TextCsvConverter().convert(payload, {})

        assert written == payload
        assert written.startswith(b"key,opened,severity,system,root_cause,recorded_loss_chf\n")

    def test_a_row_is_written_with_its_commas_and_no_table(self):
        """Counter-example, row 2: the one where a quote from a row is found as written."""
        written = TextCsvConverter().convert(REGISTER.read_bytes(), {}).decode("utf-8")

        assert "PLAY-4001,2026-04-17,major,payments-worker," in written
        assert "|" not in written

    def test_a_csv_in_windows_1252_fails_naming_utf8(self):
        """Counter-example, row 3: the one Excel saved in its own encoding."""
        payload = "key,system\nPLAY-4001,café-api\n".encode("cp1252")

        with pytest.raises(ValueError) as error:
            TextCsvConverter().convert(payload, {})

        assert "text-csv" in str(error.value) and "UTF-8" in str(error.value)

    def test_it_claims_csv_as_markdown(self):
        """The pair it answers, which nothing answered before (R8.5)."""
        converter = TextCsvConverter()

        assert (converter.id, converter.media_type, converter.kind) == (
            "text-csv",
            "text/csv",
            "markdown",
        )
