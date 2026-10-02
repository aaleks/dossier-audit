"""R4.32 — `--plan` reports a step whose last run failed documents as asking
them again, naming them.

An answer that did not validate is never cached (R6.1), so the next run asks
about that document again (R4.28 row 6). The plan found nothing edited or
synced and printed `cached`: a promise of no call, broken once per failed
document (R4.12). Here the scoring example is run with `INC-4822` answered in
prose where JSON was asked for, twice, so it fails after its retry and lands in
`failures.json` as R4.27 row 1 records it.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    Model,
    _edit_prompt,
    _workspace,
)
from tests.fakes import register_connector
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_TYPE, IssueTracker


def _ran(workspace: Path, monkeypatch, model: Model) -> list[tuple[str, str]]:
    """One run with `model`; the `(step, document)` units it recorded as failed."""
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    (failures,) = (workspace / "runs").glob("*/failures.json")
    assert failures.is_file(), result.output
    return [
        (entry["step"], entry["document"])
        for entry in json.loads(failures.read_text(encoding="utf-8"))
    ]


def _plan(workspace: Path, monkeypatch) -> list[str]:
    result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")
    assert result.exit_code == 0, result.output
    return result.stdout.splitlines()


class TestAPlanAsksAgainWhatTheLastRunFailed:
    """R4.32 — a failed document is no cache entry, and the plan says it will be asked."""

    def test_a_failed_document_is_named_as_asked_again(self, workspace, monkeypatch):
        """Row 1 — the one whose last run failed `INC-4822` at `extract`."""
        _workspace(workspace, monkeypatch)
        assert _ran(workspace, monkeypatch, Model(failing="INC-4822")) == [
            ("extract", "INC-4822")
        ]

        lines = _plan(workspace, monkeypatch)

        at = lines.index("! extract: failed last run")
        assert lines[at + 1] == "      moved: [INC-4822 failed]"
        assert "1 of 1 step(s) would run · nothing written" in lines

    def test_a_step_reading_it_runs_again_too(self, workspace, monkeypatch):
        """Row 2 — the one with `verify` reading `extract`."""
        _workspace(
            workspace,
            monkeypatch,
            steps=["extract", "verify"],
            inputs={"verify": "extract"},
            outputs={"verify": None},
        )
        assert _ran(workspace, monkeypatch, Model(failing="INC-4822")) == [
            ("extract", "INC-4822")
        ]

        lines = _plan(workspace, monkeypatch)

        assert "! extract: failed last run" in lines
        assert "! verify: upstream changed" in lines

    def test_a_run_that_failed_nothing_is_cached(self, workspace, monkeypatch):
        """Row 3, counter-example — the one whose last run failed nothing."""
        _workspace(workspace, monkeypatch)
        assert _ran(workspace, monkeypatch, Model()) == []

        lines = _plan(workspace, monkeypatch)

        assert "  extract: cached" in lines
        assert "0 of 1 step(s) would run · nothing written" in lines

    def test_a_moved_prompt_is_named_over_the_failure(self, workspace, monkeypatch):
        """Row 4, counter-example — the one that failed `INC-4822`, its prompt moved since."""
        _workspace(workspace, monkeypatch)
        assert _ran(workspace, monkeypatch, Model(failing="INC-4822")) == [
            ("extract", "INC-4822")
        ]
        _edit_prompt(workspace)

        lines = _plan(workspace, monkeypatch)

        assert "! extract: prompt changed" in lines
        assert not any("failed" in line for line in lines)

    def test_a_failed_document_that_left_the_source_is_not_asked(self, workspace, monkeypatch):
        """Row 5, counter-example — the one that failed `INC-4822`, tombstoned since."""
        _workspace(workspace, monkeypatch)
        assert _ran(workspace, monkeypatch, Model(failing="INC-4822")) == [
            ("extract", "INC-4822")
        ]
        remaining = {key: text for key, text in ISSUES.items() if key != "INC-4822"}
        register_connector(
            monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(remaining)
        )
        synced = _cli(workspace, monkeypatch, "sync", PIPELINE, "--full")
        assert synced.exit_code == 0, synced.output
        assert "1 tombstoned" in synced.output

        lines = _plan(workspace, monkeypatch)

        assert "  extract: cached" in lines
