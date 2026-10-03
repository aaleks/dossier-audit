"""R22.5 — a relevance gold file that does not name a query, its readers, who
judged it and grades 0 to 2 by document id is refused before any search,
naming the file and the problem.

A malformed file is refused rather than skipped: a skipped query would leave
the means quietly over fewer questions than the gold holds. Every file is read
before any is refused, so one pass names every problem, as pipeline gold does
(R7.56).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.config.load import ConfigError, load_relevance_gold
from dossier.domain.relevance import RelevanceQuery

NAME = "certificate-expired-at-checkout"
WELL_FORMED = """query: certificate expired at checkout
readers: [incident-response]
judged_by: a.aleks
judged:
  incidents-jira:INC-4830: 2
  incidents-jira:INC-4821: 0
"""


def _gold(tmp_path: Path, text: str = WELL_FORMED, name: str = NAME) -> Path:
    directory = tmp_path / "gold" / "incidents-search"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yaml").write_text(text, encoding="utf-8")
    return directory


def _refused(directory: Path) -> list[str]:
    with pytest.raises(ConfigError) as refused:
        load_relevance_gold(directory)
    return str(refused.value).splitlines()


class TestAMalformedRelevanceFileIsRefused:
    """R22.5 — refused before any search, naming the file and the problem."""

    def test_a_grade_outside_0_to_2(self, tmp_path: Path):
        """Row 1 — the one graded 3."""
        directory = _gold(tmp_path, WELL_FORMED.replace("INC-4830: 2", "INC-4830: 3"))

        assert _refused(directory) == [
            f"{NAME}.yaml: incidents-jira:INC-4830 is graded 3; a grade is 0, 1 or 2"
        ]

    def test_no_readers(self, tmp_path: Path):
        """Row 2 — the one naming no readers."""
        directory = _gold(tmp_path, WELL_FORMED.replace("readers: [incident-response]\n", ""))

        assert _refused(directory) == [
            f"{NAME}.yaml: readers is missing: a search names its readers (R19.11)"
        ]

    def test_no_one_judged_it(self, tmp_path: Path):
        """Row 3 — the one nobody signed."""
        directory = _gold(tmp_path, WELL_FORMED.replace("judged_by: a.aleks\n", ""))

        assert _refused(directory) == [
            f"{NAME}.yaml: judged_by is missing: there is no anonymous path into gold (R7.7)"
        ]

    def test_a_document_named_without_its_source(self, tmp_path: Path):
        """Row 4 — the one judging `INC-4830` with no source."""
        directory = _gold(tmp_path, WELL_FORMED.replace("incidents-jira:INC-4830", "INC-4830"))

        assert _refused(directory) == [
            f"{NAME}.yaml: INC-4830 is not a document id: a document is named <source>:<key>"
        ]

    def test_every_file_is_named_in_one_pass(self, tmp_path: Path):
        """Rows 1 and 3 together — two files, each refused for its own problem."""
        _gold(tmp_path, WELL_FORMED.replace("INC-4830: 2", "INC-4830: 3"))
        directory = _gold(
            tmp_path, WELL_FORMED.replace("judged_by: a.aleks\n", ""), name="unsigned"
        )

        assert _refused(directory) == [
            f"{NAME}.yaml: incidents-jira:INC-4830 is graded 3; a grade is 0, 1 or 2",
            "unsigned.yaml: judged_by is missing: there is no anonymous path into gold (R7.7)",
        ]

    def test_a_well_formed_file_is_read(self, tmp_path: Path):
        """Row 5, counter-example — the file as written."""
        directory = _gold(tmp_path)

        assert load_relevance_gold(directory) == [
            RelevanceQuery(
                name=NAME,
                query="certificate expired at checkout",
                readers=("incident-response",),
                judged_by="a.aleks",
                judged={"incidents-jira:INC-4830": 2, "incidents-jira:INC-4821": 0},
            )
        ]

    @pytest.mark.parametrize("made", [True, False], ids=["empty", "missing"])
    def test_a_directory_holding_no_relevance_gold(self, tmp_path: Path, made: bool):
        """Row 6 — the one with no `.yaml` file in it, or no directory at all."""
        directory = tmp_path / "gold" / "incidents-search"
        if made:
            directory.mkdir(parents=True)
            (directory / "notes.md").write_text("judged on 2026-10-03\n", encoding="utf-8")

        assert _refused(directory) == [f"{directory}: no relevance gold in it (*.yaml)"]
