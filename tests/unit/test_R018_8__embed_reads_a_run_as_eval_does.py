"""R18.8 rows 7 and 8 — `embed` reads the latest run as `eval` does: reproduced
from its manifest and the cache, never from the copies under `runs/`.

The copies are for people, and may be edited without any later command
noticing (R0.11). Read back, a reviewer's edit would change what the index
filters on while `eval` went on scoring the cached answer.

Through the CLI, over R18.11's workspace: `INC-4830` synced and run, its
taxonomy extracted, and the index declared.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance import test_R018_11__embed_carries_the_runs_record as carried
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import (
    INDEX,
    ROOT_CAUSE,
    _document,
    _latest_run,
    _records,
)

# R18.11's workspace, its fixtures shared rather than copied.
issues, embedder, index, run_once = (
    carried.issues,
    carried.embedder,
    carried.index,
    carried.run_once,
)


def _copy(workspace: Path, run: str) -> Path:
    return workspace / "runs" / run / "extract" / "INC-4830.json"


class TestEmbedReadsARunAsEvalDoes:
    """R18.8 rows 7 and 8 — the cache is where a run's answers are read."""

    def test_a_run_that_cannot_be_replayed_carries_no_record(
        self, run_once: Path, monkeypatch, index
    ):
        """Row 7, counter-example — the one whose `extract` entry was deleted."""
        run = _latest_run(run_once)
        meta = _copy(run_once, run).with_name("INC-4830.meta.json")
        key = json.loads(meta.read_text(encoding="utf-8"))["cache_key"]
        stage = run_once / ".dossier" / "cache" / "stage" / key[:2] / key[2:4]
        for path in stage.glob(f"{key}*"):
            path.unlink()

        result = _cli(run_once, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        named = [line for line in result.output.splitlines() if "cannot be replayed" in line]
        assert len(named) == 1, result.output
        assert named[0].startswith(f"no record: {run} cannot be replayed: "), named
        assert _document(index).values == {}
        assert _document(index).run_id is None
        assert _records(index) == []

    def test_a_reviewers_edit_of_the_copy_is_not_carried(
        self, run_once: Path, monkeypatch, index
    ):
        """Row 8, counter-example — the one where `runs/` was edited by hand."""
        copy = _copy(run_once, _latest_run(run_once))
        text = copy.read_text(encoding="utf-8")
        assert '"checkout"' in text
        copy.write_text(text.replace('"checkout"', '"payments-api"'), encoding="utf-8")

        result = _cli(run_once, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert _document(index).values["component"] == "checkout"
        assert [chunk.text for chunk in _records(index)] == [f"root_cause: {ROOT_CAUSE}"]
