"""R16.8 — `gc` deletes no cache entry while a kept run's replay stops before
its stages.

A replay reads a run's snapshots and conversions before it asks for any stage's
answer (R4.7). With `.dossier/cache/convert` deleted -- safe for the next run,
R5.9 -- a kept run's replay stops with not one stage key read, and collecting
then would delete the model's answers: the one part no command remakes.
`dossier convert` would have made the run replay again.

Through the CLI, over R16.7's workspace: `extract`, `notes` and `verify` over
the scoring example, run twice.
"""

from __future__ import annotations

import json
import shutil
from itertools import count
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    AFTER,
    Model,
    _workspace,
)
from tests.fakes import NoModelClient
from tests.scoring_example import PIPELINE
from tests.unit.test_R016_7__an_unreplayable_kept_run_does_not_stop_gc import (
    KEPT_AS_IT_IS,
    _killed_during_verify,
)

NOT_TRACED = (
    "  no cache entry deleted: runs/{run}/ stopped before its stages, "
    "so the entries it reads cannot be traced"
)


def _two_runs(workspace: Path, monkeypatch) -> list[str]:
    """Two runs of the pipeline, by run id; the model then refused."""
    import dossier.cli.bootstrap as cli

    suffixes = count(1)
    monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: f"{next(suffixes):04x}")
    _workspace(workspace, monkeypatch, **AFTER)
    for _ in range(2):
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return sorted(path.name for path in (workspace / "runs").iterdir())


def _stage_keys(workspace: Path) -> set[str]:
    """Every stage entry a run under `runs/` read, from the records it filed."""
    return {
        json.loads(record.read_text(encoding="utf-8"))["cache_key"]
        for record in (workspace / "runs").glob("*/*/*.meta.json")
    }


def _held(workspace: Path, key: str) -> bool:
    return (workspace / ".dossier" / "cache" / "stage" / key[:2] / key[2:4] / key).is_file()


def _delete_conversions(workspace: Path) -> None:
    shutil.rmtree(workspace / ".dossier" / "cache" / "convert")


class TestARunThatStopsBeforeItsStagesKeepsEveryEntry:
    """R16.8 — nothing collected from either cache until every kept run traces."""

    def test_every_stage_entry_is_kept_and_each_run_is_named(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one where the conversions were deleted, as R5.9 allows."""
        runs = _two_runs(workspace, monkeypatch)
        read = _stage_keys(workspace)
        assert read and all(_held(workspace, key) for key in read)
        _delete_conversions(workspace)

        result = _cli(workspace, monkeypatch, "gc", "--apply")

        assert result.exit_code == 0, result.output
        lost = sorted(key for key in read if not _held(workspace, key))
        assert lost == [], f"gc deleted {len(lost)} of {len(read)} stage entries"
        errors = result.stderr.splitlines()
        for run in runs:
            named = errors.index(NOT_TRACED.format(run=run))
            assert errors[named - 1].startswith(KEPT_AS_IT_IS.format(run=run)), errors

    def test_dossier_convert_then_makes_the_run_replay(self, workspace: Path, monkeypatch):
        """Row 2 — the one where the run is still one deterministic command away."""
        latest = _two_runs(workspace, monkeypatch)[-1]
        _delete_conversions(workspace)
        assert _cli(workspace, monkeypatch, "gc", "--apply").exit_code == 0

        assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{latest}")

        assert result.exit_code == 0, result.output
        assert "no model calls" in result.output

    def test_a_run_directory_is_still_deleted(self, workspace: Path, monkeypatch):
        """Row 3 — the one where the older run goes, and no entry with it."""
        older, latest = _two_runs(workspace, monkeypatch)
        read = _stage_keys(workspace)
        _delete_conversions(workspace)

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        summary = result.stdout.splitlines()[0]
        assert summary.startswith("freed "), summary
        assert summary.endswith(": 1 run, 0 tries, 0 replays, 0 cache entries"), summary
        assert not (workspace / "runs" / older).exists()
        assert (workspace / "runs" / latest).is_dir()
        assert all(_held(workspace, key) for key in read)

    def test_a_run_that_reached_its_stages_is_traced_as_before(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, counter-example — the one killed during `verify` (R16.7)."""
        from dossier.infrastructure.cache import ArtifactCache

        _killed_during_verify(workspace, monkeypatch)
        orphan = "0" * 64
        ArtifactCache(workspace, namespace="stage").put(
            orphan, b"{}", record={"cache_key": orphan}
        )

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        assert not _held(workspace, orphan), "an entry no run reads is collected"
        assert "no cache entry deleted" not in result.stderr
