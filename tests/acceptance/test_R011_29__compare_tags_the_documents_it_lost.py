"""R11.29 — a comparison names the documents the change lost on its run, as
`dossier.lost`.

R7.55 marks a document `b` failed and `a` answered as a regression, and keeps it
out of `dossier.regressed`, which names fields. The marker reached the terminal
and `deltas.md` and nothing a person can filter on: a comparison whose change
broke a document was tagged `dossier.regressed` empty, as one that changed
nothing is. Decided by `a.aleks` on 2026-09-30.

The slice's acceptance rule, through the CLI with tracking on and a
`FakeTracker`, over R7.54's two runs: the scoring example, the prompt edited
between them, and a document named to fail `extract` after its retry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    GOLD,
    NOT_JSON,
    URI,
)
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _two_runs,
    _workspace,
)
from tests.fakes import FakeTracker, NoModelClient
from tests.scoring_example import PIPELINE

pytestmark = pytest.mark.outer_loop


class Failing(Model):
    """The scoring example's answers, with every document in `documents` failing `extract`."""

    def __init__(self, *documents: str) -> None:
        super().__init__()
        self.documents = documents

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if schema is not None and any(f"# {name}\n" in prompt for name in self.documents):
            self.calls.append("failing")
            return NOT_JSON
        return super().complete(prompt, schema=schema, parts=parts)


def _tags(workspace: Path, monkeypatch, a: Model, b: Model) -> dict[str, str]:
    """The tags of the comparison of a run answered by `a` with one answered by `b`."""
    import dossier.cli.bootstrap as cli

    _workspace(workspace, monkeypatch)
    first, second = _two_runs(workspace, monkeypatch, a, b)
    tracker = FakeTracker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)

    result = _cli(
        workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", first, second
    )

    assert result.exit_code == 0, result.output
    (run,) = tracker.runs
    return run.tags


class TestCompareTagsTheDocumentsItLost:
    """R11.29 — the documents the change lost, named where they can be filtered on."""

    def test_a_document_the_change_lost_is_tagged(self, workspace: Path, monkeypatch):
        """Row 1 — the one where `b` failed INC-4822, which `a` answered."""
        tags = _tags(workspace, monkeypatch, Model(), Model(failing="INC-4822"))

        assert tags["dossier.lost"] == "INC-4822"
        # It names fields, and no field moved: R7.55 keeps documents out of it.
        assert tags["dossier.regressed"] == ""

    def test_every_document_the_change_lost_is_tagged(self, workspace: Path, monkeypatch):
        """Row 2 — the one where `b` lost two, named in the order the terminal names them."""
        tags = _tags(workspace, monkeypatch, Model(), Failing("INC-4822", "INC-4901"))

        assert tags["dossier.lost"] == "INC-4822, INC-4901"

    def test_a_document_the_change_recovered_is_not_tagged(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where `a` failed it and `b` answered it."""
        tags = _tags(workspace, monkeypatch, Model(failing="INC-4822"), Model())

        assert tags["dossier.lost"] == ""

    def test_a_document_both_runs_failed_is_not_tagged(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where the change lost nothing."""
        tags = _tags(
            workspace, monkeypatch, Model(failing="INC-4822"), Model(failing="INC-4822")
        )

        assert tags["dossier.lost"] == ""

    def test_a_comparison_that_lost_nothing_says_so(self, workspace: Path, monkeypatch):
        """Row 5, counter-example — the one where neither run failed, and the tag is there."""
        tags = _tags(workspace, monkeypatch, Model(), Model())

        assert tags["dossier.lost"] == ""
