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
from tests.unit import test_R002_17__a_held_document_is_its_raw_snapshot as projected

from dossier.application.gc import gc_plan
from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.domain.ledger import LedgerRow
from dossier.domain.sync import State

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
        workspace,
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

    def test_the_judge_cache_snapshots_and_ledger_keep_every_byte(
        self, workspace: Path, monkeypatch
    ):
        """Row 6, counter-example — the one where `--apply` deleted, and none of these.

        Over row 5's workspace, so a superseded snapshot is held beside the
        current one, and `gc` does delete: the earlier run and its conversion.
        """
        tracker = _workspace(workspace, monkeypatch)
        earlier = _run(workspace, monkeypatch)
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        _cache_entry(workspace, "judge")
        untouched = (".dossier/cache/judge", ".dossier/snapshots", ".dossier/ledger.db")
        before = _bytes(workspace, *untouched)
        assert len(_bytes(workspace, ".dossier/snapshots")) > len(ISSUES), "one superseded"

        result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", "--apply")

        assert result.exit_code == 0, result.output
        assert not (workspace / "runs" / earlier).exists(), "gc --apply deleted"
        assert _bytes(workspace, *untouched) == before

    def test_the_embed_cache_keeps_every_byte(self, workspace: Path, monkeypatch):
        """Row 8, counter-example — the one holding the vectors an index is rebuilt from."""
        tracker = _workspace(workspace, monkeypatch)
        earlier = _run(workspace, monkeypatch)
        tracker.issues["INC-4821"] = CHANGED
        _sync(workspace, monkeypatch)
        _run(workspace, monkeypatch)
        _cache_entry(workspace, "embed")
        before = _bytes(workspace, ".dossier/cache/embed")

        for more in ((), ("--apply",)):
            result = _cli(workspace, monkeypatch, "gc", "--keep-last", "1", *more)

            assert result.exit_code == 0, result.output
            assert _bytes(workspace, ".dossier/cache/embed") == before, more
        assert not (workspace / "runs" / earlier).exists(), "gc --apply deleted"

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
    return row.snapshot


def _cache_entry(workspace: Path, namespace: str) -> None:
    """One entry, with its provenance record, in a cache `gc` does not collect."""
    from dossier.infrastructure.cache import ArtifactCache

    key = "abcd" + "0" * 60
    ArtifactCache(workspace, namespace=namespace).put(key, b"[0.25, 0.5]", record={"key": key})


def _bytes(workspace: Path, *paths: str) -> dict[str, bytes]:
    """Every file under `paths`, by its path in the workspace."""
    found = {}
    for top in paths:
        root = workspace / top
        for path in sorted([root] if root.is_file() else root.rglob("*")):
            if path.is_file():
                found[path.relative_to(workspace).as_posix()] = path.read_bytes()
    assert found, f"nothing under {paths}"
    return found


# R2.17's workspace: a tracker whose source declares `fields`, synced once, so
# its row's `content_hash` is the projection's and its snapshot the raw payload's.
tracker = projected.tracker


def _row(**fields) -> LedgerRow:
    when = "2026-08-06T09:00:00Z"
    return LedgerRow(
        source_id="incidents-jira",
        key="INC-4821",
        remote_version="v37",
        media_type="text/markdown",
        first_seen=when,
        last_seen=when,
        **fields,
    )


class TestWhatIsHeldIsTheRawSnapshot:
    """R16.3 row 7 — a held document is the payload its row addresses (R2.17)."""

    def test_the_held_snapshot_is_the_one_the_row_addresses(self):
        """Row 7 — the one whose `content_hash` is a projection's, and not its snapshot."""
        from dossier.domain.gc import held_snapshots
        from dossier.domain.store import snapshot_path

        raw = "a3f9c1e2" * 8
        row = _row(content_hash="b7d0" * 16, snapshot_path=snapshot_path(raw))

        assert held_snapshots([row]) == {raw}

    def test_a_tombstoned_row_holds_nothing(self):
        """Row 5, counter-example — the one that left scope, whose conversion is not read."""
        from dossier.domain.gc import held_snapshots
        from dossier.domain.store import snapshot_path

        raw = "a3f9c1e2" * 8
        row = _row(content_hash=raw, snapshot_path=snapshot_path(raw), state=State.TOMBSTONED)

        assert held_snapshots([row]) == set()

    def test_gc_keeps_the_conversion_of_a_held_projected_document(
        self, workspace: Path, monkeypatch, tracker
    ):
        """Row 7 — the one synced from a source declaring `fields`, then `gc --apply`."""
        (row,) = projected._rows(workspace, "incidents-jira")
        assert row.content_hash != row.snapshot, "the projection's hash is not the payload's"
        assert _cli(workspace, monkeypatch, "convert", projected.PIPELINE).exit_code == 0
        converted = _conversions(workspace, row.snapshot)
        assert converted, "`dossier convert` wrote the held snapshot's conversion"

        result = _cli(workspace, monkeypatch, "gc", "--apply")

        assert result.exit_code == 0, result.output
        assert converted <= _conversions(workspace, row.snapshot), result.output
