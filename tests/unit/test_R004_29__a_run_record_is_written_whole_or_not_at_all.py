"""R4.29 — a run's `manifest.json` and `failures.json` are each written whole,
or not at all.

Each was written in place, so a process killed while writing one left it cut
short, the case `gc` had to tolerate (R16.11). Now each is written beside itself
and renamed over the real one. Here the rename is stopped, as a process killed
just before it would be, and nothing of the file is where a reader looks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.run import write_failures
from dossier.domain.resolution import PinnedDocument, ResolvedPlan
from dossier.domain.store import FAILURES_NAME

RUN_ID = "20260806T142203Z-4f1a"
FAILED = [
    {
        "step": "extract",
        "document": "INC-4822",
        "part": None,
        "reason": "no valid output after 2 attempts: Invalid JSON",
    }
]


def manifest() -> Manifest:
    return Manifest(
        run_id=RUN_ID,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        plan=ResolvedPlan(
            pipeline="incident-audit",
            pipeline_hash="2f60a7d3",
            model="anthropic:claude-sonnet-4-5-20250929",
            steps=[],
            documents=[PinnedDocument(key="INC-4821", snapshot="snapshots/INC-4821")],
        ),
    )


class Stopped(Exception):
    """The process, stopped between writing the temporary file and renaming it."""


@pytest.fixture
def stopped_before_the_rename(monkeypatch):
    import dossier.application.manifest as written

    def stop(source, target):
        raise Stopped(f"{source} -> {target}")

    monkeypatch.setattr(written, "_rename", stop)


class TestARunRecordIsWrittenWholeOrNotAtAll:
    """R4.29 — a whole file, or none."""

    def test_a_manifest_stopped_before_its_rename_is_not_there(
        self, tmp_path: Path, stopped_before_the_rename
    ):
        """Row 1 — the one stopped after the temporary file and before the rename."""
        with pytest.raises(Stopped):
            manifest().write(tmp_path)

        assert not (tmp_path / RUN_ID / MANIFEST_NAME).exists()

    def test_failures_stopped_before_their_rename_are_not_there(
        self, tmp_path: Path, stopped_before_the_rename
    ):
        """Row 2 — the one whose `failures.json` was stopped the same way."""
        (tmp_path / RUN_ID).mkdir()

        with pytest.raises(Stopped):
            write_failures(tmp_path / RUN_ID, FAILED)

        assert not (tmp_path / RUN_ID / FAILURES_NAME).exists()

    def test_both_written_to_the_end_are_whole_with_nothing_beside_them(self, tmp_path: Path):
        """Row 3, counter-example — the one that was not stopped."""
        written = manifest().write(tmp_path)
        write_failures(tmp_path / RUN_ID, FAILED)

        assert Manifest.read(written) == manifest()
        assert json.loads((tmp_path / RUN_ID / FAILURES_NAME).read_text(encoding="utf-8")) == (
            FAILED
        )
        assert sorted(path.name for path in (tmp_path / RUN_ID).iterdir()) == [
            FAILURES_NAME,
            MANIFEST_NAME,
        ]
