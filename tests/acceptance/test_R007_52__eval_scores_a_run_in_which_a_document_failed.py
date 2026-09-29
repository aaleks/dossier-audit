"""R7.52 — `dossier eval` scores a run in which a document failed, counts the
failures in its headline, and names each one.

The slice's acceptance rule. R7.50 row 6 says a failed document is not scored
and is reported as failed. It was proved on the scorer alone: through the CLI,
`eval` scores a replay (R7.10), and the replay stopped on the failed document's
missing entry, exit 2. So one failure made a whole run unscorable.

The four incidents of `_fixtures.md`'s scoring example, answered as it answers
them, except that `INC-4822` answers prose on both attempts and fails `extract`
(R6.2). `root_cause` is abstained on everywhere, so `eval` has nothing to judge:
no model is asked, and a `NoModelClient` would say so if one were (R7.10).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
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
    abstains,
)

pytestmark = pytest.mark.outer_loop

GOLD = "gold/incidents"
URI = "http://localhost:5000"
FAILED = "INC-4822"
NOT_JSON = "not JSON at all"
REASON = "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
# Nothing to judge: every `root_cause` abstains, so a model call in `eval` is a
# finding rather than a judge doing its job.
ANSWERED = {
    document: [
        abstains("root_cause") if record.get("field") == "root_cause" else record
        for record in records
    ]
    for document, records in ANSWERS.items()
}


class FailingOne(RoutedModel):
    """The scoring example's answers, except that `failing` is answered with prose."""

    def __init__(self, answers, *, failing: str | None) -> None:
        super().__init__(answers)
        self.failing = failing

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if self.failing is not None and f"# {self.failing}\n" in prompt:
            self.calls.append(self.failing)
            return NOT_JSON
        return super().complete(prompt, schema=schema, parts=parts)


def _run(workspace: Path, monkeypatch, *, failing: str | None = FAILED) -> FailingOne:
    """Sync the four incidents and run `extract` over them; the model."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    model = FailingOne(ANSWERED, failing=failing)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == (0 if failing is None else 1), ran.output
    return model


def _eval(workspace: Path, monkeypatch, *, tracker=None):
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    if tracker is not None:
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


def _headline(output: str) -> str:
    return next((line for line in output.splitlines() if " fields · overall " in line), "")


class TestEvalScoresARunInWhichADocumentFailed:
    """R7.52 — the rest scored, the failure counted in the headline and named."""

    def test_the_other_three_are_scored_and_the_failure_named(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one where one incident of four answered prose twice."""
        model = _run(workspace, monkeypatch)
        assert model.calls.count(FAILED) == 2, "the failed incident was asked twice (R6.2)"

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert re.fullmatch(
            r"3 documents · \d+ fields · overall \d+\.\d% · 1 failed", _headline(result.output)
        ), result.output
        assert f"  not scored: {FAILED} failed at extract: {REASON}" in (
            result.output.splitlines()
        ), result.output

    def test_the_eval_record_counts_the_failure(self, workspace: Path, monkeypatch):
        """Row 2 — the one where MLflow holds the count the terminal printed."""
        from tests.fakes import FakeTracker

        _run(workspace, monkeypatch)
        recorder = FakeTracker()

        result = _eval(workspace, monkeypatch, tracker=recorder)

        assert result.exit_code == 0, result.output
        (run,) = recorder.runs
        assert run.metrics["failed"] == 1

    def test_a_run_that_failed_nothing_is_reported_as_before(
        self, workspace: Path, monkeypatch
    ):
        """Row 3, counter-example — the one with no failure to count or name."""
        from tests.fakes import FakeTracker

        _run(workspace, monkeypatch, failing=None)
        recorder = FakeTracker()

        result = _eval(workspace, monkeypatch, tracker=recorder)

        assert result.exit_code == 0, result.output
        assert re.fullmatch(
            r"4 documents · \d+ fields · overall \d+\.\d%", _headline(result.output)
        ), result.output
        assert "not scored" not in result.output
        (run,) = recorder.runs
        assert "failed" not in run.metrics
