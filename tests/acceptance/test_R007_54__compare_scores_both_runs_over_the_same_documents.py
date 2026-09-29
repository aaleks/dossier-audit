"""R7.54 — `--compare` scores both runs over the same documents: a document
either run left unscored is scored in neither.

The slice's acceptance rule. Since R4.28 a replay reproduces a failed
document, so a comparison no longer stopped on one. It scored the run that
failed `INC-4822` over three documents and the other over four, and
`resolution_date` and `affected_systems` each read `75.0%  66.7%  -8.3   <-
regression`, when nothing had changed but the failure. Found by `/verify` on
2026-09-29.

The four incidents of `_fixtures.md`'s scoring example, answered as it answers
them. A document named to fail answers prose on both attempts, and fails
`extract` after its retry (R6.2). The prompt is edited between the two runs, as
R7.8's test does, so the second is asked afresh rather than served the first's
answers (R5.2). `root_cause` is abstained on everywhere, so neither `eval` nor
the comparison has anything to judge, and a `NoModelClient` would say so if a
model were asked (R7.10).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    ANSWERED,
    GOLD,
    NOT_JSON,
)
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

# `notes` and `verify` after `extract`, as R6.29 row 2 has them: `verify` reads
# `notes`, and a `notes` answered with the empty string fails it (R7.53 row 4).
AFTER = {
    "steps": ["extract", "notes", "verify"],
    "inputs": {"notes": "documents", "verify": "notes"},
    "outputs": {"notes": None, "verify": None},
}


class Model(RoutedModel):
    """The scoring example's answers; `failing` answers prose, `silent` gets an empty note."""

    def __init__(self, *, failing: str | None = None, silent: str | None = None) -> None:
        super().__init__(ANSWERED)
        self.failing = failing
        self.silent = silent

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if schema is None:
            # A step with no `output`: `notes` or `verify`, answered in prose.
            self.calls.append("prose")
            return "" if self.silent and f"# {self.silent}\n" in prompt else "Read and noted."
        if self.failing is not None and f"# {self.failing}\n" in prompt:
            self.calls.append(self.failing)
            return NOT_JSON
        return super().complete(prompt, schema=schema, parts=parts)


def _workspace(workspace: Path, monkeypatch, **pipeline) -> None:
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID], **pipeline)
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0


def _run(workspace: Path, monkeypatch, model: Model) -> str:
    """Run the pipeline with `model`; the run id."""
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert model.call_count > 0, "the prompt changed, so the model must be asked afresh"
    return re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)


def _edit_prompt(workspace: Path, step: str = "extract") -> None:
    """A prompt change between the runs, so the second is asked afresh (R5.2)."""
    prompt = workspace / "pipelines" / PIPELINE / "prompts" / f"{step}.md"
    prompt.write_text(
        "Read carefully; cite only what the document states.\n"
        + prompt.read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _two_runs(workspace: Path, monkeypatch, a: Model, b: Model, *, step: str = "extract"):
    first = _run(workspace, monkeypatch, a)
    _edit_prompt(workspace, step)
    return first, _run(workspace, monkeypatch, b)


def _compare(workspace: Path, monkeypatch, a: str, b: str):
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", a, b)


def _headline(output: str) -> str:
    return next((line for line in output.splitlines() if line.startswith("compare ")), "")


def _row(output: str, field: str) -> str:
    return next((line for line in output.splitlines() if line.startswith(f"  {field} ")), "")


class TestCompareScoresBothRunsOverTheSameDocuments:
    """R7.54 — a document either run left unscored is scored in neither."""

    def test_a_failure_is_not_read_as_a_regression(self, workspace: Path, monkeypatch):
        """Row 1 — the one where a failure looked like a regression."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(workspace, monkeypatch, Model(), Model(failing="INC-4822"))

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert re.fullmatch(
            rf"compare {a} -> {b} · 3 of 4 documents · overall .*", _headline(result.output)
        ), result.output
        for field in ("resolution_date", "affected_systems"):
            assert _row(result.output, field).split()[-1] == "+0.0", result.output
        assert "<- regression" not in result.output, result.output

    def test_each_run_leaves_out_the_document_it_failed(self, workspace: Path, monkeypatch):
        """Row 2 — the one where each run failed a different document."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(
            workspace, monkeypatch, Model(failing="INC-4822"), Model(failing="INC-4901")
        )

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert re.fullmatch(
            rf"compare {a} -> {b} · 2 of 4 documents · overall .*", _headline(result.output)
        ), result.output

    def test_two_runs_that_failed_nothing_compare_every_document(
        self, workspace: Path, monkeypatch
    ):
        """Row 3, counter-example — the one where neither run failed (R7.8 row 1)."""
        _workspace(workspace, monkeypatch)
        a, b = _two_runs(workspace, monkeypatch, Model(), Model())

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert re.fullmatch(
            rf"compare {a} -> {b} · 4 documents · overall .*", _headline(result.output)
        ), result.output

    def test_a_failure_after_the_scored_step_leaves_nothing_out(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, counter-example — the one where `verify`, after `extract`, failed it."""
        _workspace(workspace, monkeypatch, **AFTER)
        a, b = _two_runs(
            workspace, monkeypatch, Model(), Model(silent="INC-4821"), step="notes"
        )
        recorded = json.loads((workspace / "runs" / b / "failures.json").read_text("utf-8"))
        assert [(f["step"], f["document"]) for f in recorded] == [("verify", "INC-4821")]

        result = _compare(workspace, monkeypatch, a, b)

        assert result.exit_code == 0, result.output
        assert re.fullmatch(
            rf"compare {a} -> {b} · 4 documents · overall .*", _headline(result.output)
        ), result.output
