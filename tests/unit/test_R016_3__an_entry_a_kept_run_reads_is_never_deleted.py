"""R16.3 — `gc` deletes a stage or convert entry only when no kept run's replay
reads it and, for a conversion, its snapshot is not held now.

A kept run is reproduced from its manifest and the cache, its answers and
conversions read by key (R4.7). So the entries its replay reads survive,
whichever run first wrote them: two runs that asked the same question share one
entry, and a try's answer is the entry a later run is served (R4.21). A
conversion of a snapshot the ledger holds now is kept too: the next run reads it.

Through `gc_plan`, what `dossier gc` would delete, over a workspace the CLI made:
the scoring example's four incidents, from one tracker a test can change between
syncs. `--keep-last 1` throughout, so the earlier run is the one deleted. Its
suffix is pinned below the later run's, so run-id order is the order they ran.
"""

from __future__ import annotations

import json
import re
from itertools import count
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_52__eval_scores_a_run_in_which_a_document_failed import (
    ANSWERED,
)
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.gc import gc_plan
from dossier.application.manifest import MANIFEST_NAME, Manifest

CHANGED = ISSUES["INC-4821"] + "Reopened on 2026-08-09 for a follow-up.\n"


def _workspace(workspace: Path, monkeypatch) -> IssueTracker:
    """The four incidents synced from one tracker, which the test may change."""
    suffixes = count(1)
    monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: f"{next(suffixes):04x}")
    tracker = IssueTracker(ISSUES)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: tracker)
    _sync(workspace, monkeypatch)
    return tracker


def _sync(workspace: Path, monkeypatch) -> None:
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0


def _run(workspace: Path, monkeypatch, *more: str) -> str:
    """`dossier run`, with `more` arguments; the run or try id."""
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERED))
    result = _cli(workspace, monkeypatch, "run", PIPELINE, *more)
    assert result.exit_code == 0, result.output
    # The id on the line that opens a run or a try: a source that moved since
    # the last run is warned about before it (R4.9 row 4).
    return re.search(r"^(?:run|try) (\S+)", result.output, re.MULTILINE).group(1)


def _edit_prompt(workspace: Path) -> None:
    prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
    prompt.write_text("Read carefully.\n" + prompt.read_text(encoding="utf-8"), "utf-8")


def _stage_key(workspace: Path, top: str, run: str, document: str) -> str:
    record = workspace / top / run / "extract" / f"{document}.meta.json"
    return json.loads(record.read_text(encoding="utf-8"))["cache_key"]


def _snapshot(workspace: Path, run: str, document: str) -> str:
    plan = Manifest.read(workspace / "runs" / run / MANIFEST_NAME).plan
    return next(pinned.snapshot for pinned in plan.documents if pinned.key == document)


def _conversions(workspace: Path, snapshot: str) -> set[str]:
    """The convert entries whose provenance record names `snapshot`."""
    records = (workspace / ".dossier" / "cache" / "convert").rglob("*.meta.json")
    return {
        record.name.removesuffix(".meta.json")
        for record in records
        if json.loads(record.read_text(encoding="utf-8"))["snapshot"] == snapshot
    }


def _plan(workspace: Path, *, keep_last: int = 1):
    """What `gc --keep-last N` would delete, over the real stores and the ledger."""
    from dossier.infrastructure.cache import ArtifactCache
    from dossier.infrastructure.store import SnapshotStore

    return gc_plan(
        runs=workspace / "runs",
        store=SnapshotStore(workspace),
        caches={
            name: ArtifactCache(workspace, namespace=name) for name in ("stage", "convert")
        },
        held={_held_snapshot(workspace, key) for key in ISSUES},
        keep_last=keep_last,
    )


def _deleted(workspace: Path, namespace: str, *, keep_last: int = 1) -> set[str]:
    planned = _plan(workspace, keep_last=keep_last).entries
    return {entry.key for entry in planned if entry.namespace == namespace}


class TestAnEntryAKeptRunReadsIsNeverDeleted:
    """R16.3 — only what no kept run's replay reads, and no conversion of what is held."""

    def test_an_answer_only_the_deleted_run_read_is_deleted(self, workspace: Path, monkeypatch):
        """Row 1 — the one where INC-4821 changed, so the earlier run's answer is its own."""
        tracker = _workspace(workspace, monkeypatch)
        earlier = _run(workspace, monkeypatch)
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        later = _run(workspace, monkeypatch)
        own = _stage_key(workspace, "runs", earlier, "INC-4821")
        assert own != _stage_key(workspace, "runs", later, "INC-4821")

        assert own in _deleted(workspace, "stage")

    def test_an_answer_a_kept_run_shares_is_kept(self, workspace: Path, monkeypatch):
        """Row 2 — the one where INC-4822 did not change, so both runs read one entry."""
        tracker = _workspace(workspace, monkeypatch)
        earlier = _run(workspace, monkeypatch)
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        later = _run(workspace, monkeypatch)
        shared = _stage_key(workspace, "runs", later, "INC-4822")
        assert shared == _stage_key(workspace, "runs", earlier, "INC-4822")

        assert shared not in _deleted(workspace, "stage")

    def test_a_tried_answer_a_kept_run_was_served_is_kept(self, workspace: Path, monkeypatch):
        """Row 3 — the one where a try asked first, and the kept run was served it (R4.21)."""
        _workspace(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        _edit_prompt(workspace)
        tried = _run(workspace, monkeypatch, "--doc", "INC-4901")
        later = _run(workspace, monkeypatch)
        served = _stage_key(workspace, "tries", tried, "INC-4901")
        assert served == _stage_key(workspace, "runs", later, "INC-4901")

        assert served not in _deleted(workspace, "stage")

    def test_a_conversion_of_what_is_held_now_is_kept(self, workspace: Path, monkeypatch):
        """Row 4 — the one converted after the latest run, which no run has read."""
        tracker = _workspace(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        latest = _run(workspace, monkeypatch)
        before = _snapshot(workspace, latest, "INC-4821")
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
        converted = {
            key
            for key in _conversions(workspace, _held_snapshot(workspace, "INC-4821"))
            if key not in _conversions(workspace, before)
        }
        assert converted, "`dossier convert` wrote the current snapshot's conversion"

        assert not converted & _deleted(workspace, "convert")

    def test_a_conversion_of_a_snapshot_no_longer_held_is_deleted(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, counter-example — the one of INC-4821's previous snapshot."""
        tracker = _workspace(workspace, monkeypatch)
        earlier = _run(workspace, monkeypatch)
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        previous = _conversions(workspace, _snapshot(workspace, earlier, "INC-4821"))
        assert previous

        assert previous <= _deleted(workspace, "convert")

    def test_the_judge_cache_is_never_considered(self, workspace: Path, monkeypatch):
        """Row 6, counter-example — the one where only stage and convert entries are named."""
        _workspace(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        verdict = workspace / ".dossier" / "cache" / "judge" / "ab" / "cd" / ("abcd" + "0" * 60)
        verdict.parent.mkdir(parents=True)
        verdict.write_text("{}", encoding="utf-8")

        planned = _plan(workspace).entries

        assert {entry.namespace for entry in planned} <= {"stage", "convert"}

    def test_a_kept_runs_conversion_is_kept_though_no_longer_held(
        self, workspace: Path, monkeypatch
    ):
        """Row 7 — the one where the earlier run is kept, and read a snapshot since replaced."""
        tracker = _workspace(workspace, monkeypatch)
        earlier = _run(workspace, monkeypatch)
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        previous = _snapshot(workspace, earlier, "INC-4821")
        assert previous != _held_snapshot(workspace, "INC-4821")
        read = _conversions(workspace, previous)
        assert read

        assert not read & _deleted(workspace, "convert", keep_last=2)


def _held_snapshot(workspace: Path, key: str) -> str:
    """The snapshot of `key` the ledger holds now."""
    from dossier.infrastructure.ledger import Ledger

    with Ledger(workspace) as ledger:
        (row,) = [row for row in ledger.rows(SOURCE_ID) if row.key == key]
    return row.content_hash
