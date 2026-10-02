"""R4.33 — `dossier eval` and `dossier embed` read the latest run that finished,
and name each newer run that has not.

A run that stopped before it ended cannot be reproduced: the documents it never
asked about have no cache entry. `eval` stopped on the first of them and scored
nothing, though the run before was whole; `embed` carried no fields. Here a run
is stopped for real, by a model that dies partway, as a kill would end it: its
manifest written, what it answered cached, and no `failures.json`. A run made
in the same second as another is filed after it (R0.15), so the latest is the
last one made.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.acceptance import test_R018_11__embed_carries_the_runs_record as carried
from tests.acceptance.conftest import GOLD, _calibrate, _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _edit_prompt,
    _workspace,
)
from tests.scoring_example import ANSWERS, PIPELINE, RoutedModel

STOPPED = re.compile(
    r"^  passed over: runs/(\S+)/ has no failures\.json: "
    r"it stopped before it ended, or has not ended yet$"
)
NO_RUN = f"{PIPELINE}: no run to score. Run `dossier run {PIPELINE}` first."

# R18.11's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once = (
    carried.issues,
    carried.embedder,
    carried.index,
    carried.run_once,
)


class Dying(Model):
    """Answers `answered` documents, then dies, as a process killed mid-run does."""

    def __init__(self, *, answered: int) -> None:
        super().__init__()
        self.answered = answered

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if self.call_count >= self.answered:
            raise RuntimeError("killed")
        return super().complete(prompt, schema=schema, parts=parts)


class DyingRouted(RoutedModel):
    """R18.11's model, dying before its first answer."""

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        raise RuntimeError("killed")


def _run(workspace: Path, monkeypatch, model) -> tuple[str, int]:
    """One run with `model`; its id and exit code."""
    import dossier.cli.bootstrap as cli

    before = {path.name for path in (workspace / "runs").glob("*")}
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    (made,) = {path.name for path in (workspace / "runs").glob("*")} - before
    return made, result.exit_code


def _stopped(workspace: Path, run: str) -> None:
    assert not (workspace / "runs" / run / "failures.json").exists()


def _passed_over(result) -> list[str]:
    return [
        found.group(1) for line in result.stderr.splitlines() if (found := STOPPED.match(line))
    ]


def _scored(workspace: Path, monkeypatch):
    _calibrate(workspace)
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


class TestEvalAndEmbedPassOverARunThatStopped:
    """R4.33 — a run that stopped is named, and the one before it is read."""

    def test_eval_scores_the_run_before_one_that_stopped(self, workspace, monkeypatch):
        """Row 1 — the one whose second run died after answering `INC-4821`."""
        _workspace(workspace, monkeypatch)
        _, code = _run(workspace, monkeypatch, Model())
        assert code == 0
        _edit_prompt(workspace)
        second, _ = _run(workspace, monkeypatch, Dying(answered=1))
        _stopped(workspace, second)

        result = _scored(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        assert "4 documents" in result.stdout

    def test_embed_carries_the_run_before_one_that_stopped(
        self, run_once: Path, monkeypatch, index
    ):
        """Row 2 — the one whose second run died before answering `INC-4830`."""
        first = carried._latest_run(run_once)
        _edit_prompt(run_once)
        second, _ = _run(run_once, monkeypatch, DyingRouted(ANSWERS))
        _stopped(run_once, second)

        result = _cli(run_once, monkeypatch, "embed", carried.INDEX)

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == [second]
        document = carried._document(index)
        assert document.run_id == first
        assert document.values == {
            "component": "checkout",
            "failure_category": "certificate-expiry",
        }

    def test_eval_with_only_a_run_that_stopped_has_nothing_to_score(
        self, workspace, monkeypatch
    ):
        """Row 3 — the one whose only run died."""
        _workspace(workspace, monkeypatch)
        only, _ = _run(workspace, monkeypatch, Dying(answered=1))
        _stopped(workspace, only)

        result = _scored(workspace, monkeypatch)

        assert result.exit_code == 2, result.output
        assert _passed_over(result) == [only]
        assert NO_RUN in result.stderr.splitlines()

    def test_a_run_that_finished_is_the_one_scored(self, workspace, monkeypatch):
        """Row 4, counter-example — the one whose second run finished."""
        _workspace(workspace, monkeypatch)
        _run(workspace, monkeypatch, Model())
        _edit_prompt(workspace)
        _, code = _run(workspace, monkeypatch, Model())
        assert code == 0

        result = _scored(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _passed_over(result) == []
        assert "passed over" not in result.stderr
