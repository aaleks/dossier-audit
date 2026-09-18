"""R7.20 — `dossier eval` scores the documents the run produced and names the
ones it did not.

Scoring reproduces a run from its manifest and its cache entries (R7.10), and a
document the run produced nothing for has no entry -- deliberately (R6.1). Before
R4.13 recorded which documents those were, one bad document made the whole audit
unscoreable: three quarters of a corpus audited perfectly well, and no way to
report any of it.

What keeps that safe rather than merely convenient is the record. A failure the
run wrote down is known; a missing entry with no such record is not, and the last
two rows are the pair that says so -- the same absence, the opposite answer.

An acceptance test because the claim is what a person reading the report sees:
which documents were scored, which were named, and that the count agrees with
both.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

GOLD = "gold/incidents"
FAILING = "INC-5455"


class PartlyUnusable(RoutedModel):
    """`RoutedModel`, except that one document never produces the declared shape.

    Both attempts, because R6.2 allows exactly one correction and a document that
    fails only the first is a document that succeeds.
    """

    def __init__(self, answers, *, failing: str) -> None:
        super().__init__(answers)
        self._failing = failing

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        if f"# {self._failing}\n" in prompt:
            self.calls.append(self._failing)
            return "The incident was reviewed and the figures look right."
        return super().complete(prompt, schema=schema)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _run(workspace: Path, monkeypatch, model) -> str:
    """Sync and run the scoring example against `model`, and give back the run id."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    _cli(workspace, monkeypatch, "run", PIPELINE)
    # Scoring asks no model for these fields (R7.10); a call here would be a
    # finding rather than a cost.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return sorted(path.name for path in (workspace / "runs").iterdir())[-1]


@pytest.fixture
def partly_failed(workspace: Path, monkeypatch) -> str:
    """The four documents run, with `INC-5455` producing nothing."""
    return _run(workspace, monkeypatch, PartlyUnusable(ANSWERS, failing=FAILING))


def _eval(workspace: Path, monkeypatch):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


def _documents_in(output: str) -> int:
    found = re.search(r"(\d+) documents? ·", output)
    assert found, f"no document count in:\n{output}"
    return int(found.group(1))


class TestEvalScoresWhatTheRunProduced:
    """R7.20 — a run that failed on one document is still worth scoring."""

    def test_the_other_documents_are_scored_and_the_failure_is_named(
        self, partly_failed: str, workspace: Path, monkeypatch
    ):
        """Example 1: the one where `extract` produced nothing for `INC-5455`.

        The other three are scored, the report counts three, and the line above
        it names the document and the step -- as a withheld field's line names
        the field and the reason (R7.15).
        """
        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert FAILING in result.output
        assert "produced nothing" in result.output
        assert "extract" in result.output
        assert _documents_in(result.output) == 3
        assert "loss_amount" in result.output, "the fields are still reported"

    def test_the_command_succeeds(self, partly_failed: str, workspace: Path, monkeypatch):
        """Example 2: the one where the exit code is asked about.

        Zero. The failure had its own non-zero exit when the run happened (R6.9),
        and this scoring did everything that could be done -- exiting non-zero
        here would report the same failure twice and make a partial audit
        indistinguishable from an unscoreable one.
        """
        assert _eval(workspace, monkeypatch).exit_code == 0

    def test_a_failed_document_verified_in_gold_is_still_not_scored(
        self, partly_failed: str, workspace: Path, monkeypatch
    ):
        """Example 3: the one where gold has answers for the failed document.

        `INC-5455` is verified in the gold set, and is still not scored: the run
        gave no answer to score, and gold cannot supply one. Scoring it would
        charge the model for an answer it never gave.
        """
        gold = json.loads(
            (workspace / "gold" / "incidents" / f"{FAILING}.json").read_text(encoding="utf-8")
        )
        assert gold["fields"], "the gold set verifies the document that failed"

        result = _eval(workspace, monkeypatch)

        assert _documents_in(result.output) == 3

    def test_a_run_where_everything_failed_scores_nothing_and_says_so(
        self, workspace: Path, monkeypatch
    ):
        """Example 4: the one where no document produced anything.

        All four named, nothing scored, and no overall figure -- there is nothing
        to average, and a `0.0%` would read as an audit that ran and found
        everything wrong.
        """

        class NothingUsable(RoutedModel):
            def complete(self, prompt: str, *, schema: dict | None = None) -> str:
                self.calls.append("?")
                return "not the declared shape"

        _run(workspace, monkeypatch, NothingUsable(ANSWERS))

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert "overall" not in result.output
        for document in ISSUES:
            assert document in result.output

    def test_a_lost_entry_with_no_recorded_failure_refuses_the_whole_command(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example (row 5): the same absence, and the opposite answer.

        This run recorded no failure, so a missing entry is something the
        workspace has lost rather than something the run produced nothing for.
        Scoring the rest would report a percentage over a set nobody chose, and
        would look exactly like a percentage over all four.
        """
        _run(workspace, monkeypatch, RoutedModel(ANSWERS))
        artifacts = [
            path
            for path in (workspace / ".dossier" / "cache" / "stage").rglob("*")
            if path.is_file() and not path.name.endswith(".meta.json")
        ]
        assert artifacts, "the run left artifacts behind"
        artifacts[0].unlink()

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 2
        assert "no cached artifact" in result.output
        assert "nothing has been substituted for it" in result.output
