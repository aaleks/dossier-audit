"""R17.3 — `dossier status` names each pipeline's latest run, with its documents
and how many of them a step failed.

The latest run is the last by run id, which sorts by when it started (R0.8), as
`dossier eval` and `dossier gc` find it (R16.2): three commands that disagreed
about which run is the latest would be three answers to one question. The run
ids are `_fixtures.md`'s three runs of `incident-audit`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from dossier.application.manifest import Manifest
from dossier.domain.resolution import PinnedDocument, ResolvedPlan
from dossier.domain.status import RunSeen, pipeline_lines

FIRST, SECOND, LATEST = (
    "20260806T142203Z-4f1a",
    "20260907T090000Z-bbbb",
    "20260925T091500Z-5e6f",
)


def run(run_id: str, *failed: str, pipeline: str = "incident-audit") -> RunSeen:
    return RunSeen(run_id=run_id, pipeline=pipeline, documents=4, failed=failed)


def write_run(runs: Path, run_id: str) -> None:
    """A run's manifest, pinning four documents, and nothing beside it."""
    Manifest(
        run_id=run_id,
        started_at=datetime(2026, 9, 25, 9, 15, tzinfo=UTC),
        dossier_version="0.1.0",
        plan=ResolvedPlan(
            pipeline="incident-audit",
            pipeline_hash="2f60a7d3",
            model="anthropic:claude-sonnet-4-5-20250929",
            steps=[],
            documents=[
                PinnedDocument(key=key, snapshot=f"snapshots/{key}")
                for key in ("INC-4821", "INC-4822", "INC-4901", "INC-5455")
            ],
        ),
    ).write(runs)


class TestStatusNamesEachPipelinesLatestRun:
    """R17.3 — the latest run of every pipeline, its documents and its failures."""

    def test_the_latest_run_is_named_with_its_documents_and_failures(self):
        """Row 1 — the one where `extract` failed `INC-4822` in the third run."""
        lines = pipeline_lines(
            ["incident-audit"], [run(SECOND), run(LATEST, "INC-4822"), run(FIRST)]
        )

        assert lines == [f"incident-audit · latest run {LATEST} · 4 documents · 1 failed"]

    def test_a_document_two_steps_failed_is_counted_once(self):
        """Row 2 — the one `notes` and `extract` both failed (R6.29).

        Counted twice, a run of four documents could report five failed, as
        `eval` once named such a document twice (R7.53 row 2).
        """
        (line,) = pipeline_lines(
            ["incident-audit"], [run(LATEST, "handover-note.md", "handover-note.md")]
        )

        assert line.endswith("· 4 documents · 1 failed")

    def test_a_pipeline_with_no_run_says_so(self):
        """Row 3, counter-example — the one `postmortem-review` has never run.

        Named first, so a pipeline with no run is seen not to end the list: every
        pipeline after it is still named (a survivor of mutation testing, found
        by the /verify of 2026-09-30).
        """
        lines = pipeline_lines(["postmortem-review", "incident-audit"], [run(LATEST)])

        assert lines == [
            "postmortem-review · no run yet",
            f"incident-audit · latest run {LATEST} · 4 documents · 0 failed",
        ]

    def test_a_directory_with_no_manifest_is_not_the_latest_run(self, tmp_path: Path):
        """Row 4, counter-example — the one a person left under `runs/`, named last.

        `runs/` is edited by people (R0.11). A directory holding no
        `manifest.json` is not a run (R16.2 row 6), however its name sorts.
        """
        from dossier.application.status import read_runs

        runs = tmp_path / "runs"
        for run_id in (FIRST, LATEST):
            write_run(runs, run_id)
        (runs / LATEST / "failures.json").write_text(
            json.dumps(
                [
                    {
                        "step": "extract",
                        "document": "INC-4822",
                        "page": None,
                        "reason": "no valid output after 2 attempts",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (runs / "20261001T000000Z-notes").mkdir()

        lines = pipeline_lines(["incident-audit"], read_runs(tmp_path))

        assert lines == [f"incident-audit · latest run {LATEST} · 4 documents · 1 failed"]

    def test_a_run_that_recorded_no_failures_does_not_say_none_failed(self, tmp_path: Path):
        """Row 5, counter-example — the one stopped before it ended.

        A run writes `failures.json` when every step has run, `[]` if nothing
        failed (R4.27). One that stopped wrote none, and neither did a run
        from before R4.27: `0 failed` would say it finished, which only `[]`
        says.
        """
        from dossier.application.status import read_runs

        write_run(tmp_path / "runs", LATEST)

        lines = pipeline_lines(["incident-audit"], read_runs(tmp_path))

        assert lines == [
            f"incident-audit · latest run {LATEST} · 4 documents · failures not recorded"
        ]
