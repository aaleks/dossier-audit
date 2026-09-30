"""R16.2 — `gc` keeps the latest N runs of each pipeline and every run holding a
`keep` file, and deletes every other run.

A run is a directory under `runs/` holding `manifest.json`, its pipeline the one
the manifest names. The latest are the last by run id, which sorts by the time
the run started (R0.8), as `dossier eval` finds the latest run. N is 5, and
`--keep-last` sets it for one invocation (decided by `a.aleks` on 2026-09-30).

Rows 1 to 5 are the decision, `kept_runs`, handed the runs held. Row 6 is how
they are found: `held_runs` reads `runs/`, and a directory with no manifest is
not among them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for

from dossier.application.gc import held_runs
from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.gc import HeldRun, kept_runs
from dossier.domain.pipeline import PipelineConfig, StepConfig

PINNED = "20260806T142203Z-4f1a"
# Seven runs of one pipeline, oldest first: `4f1a`, then six more.
SEVEN = [PINNED, *(f"2026090{n}T090000Z-000{n}" for n in range(1, 7))]


def _held(ids, *, pipeline="incident-audit", pinned=()):
    return [HeldRun(run_id=run, pipeline=pipeline, pinned=run in pinned) for run in ids]


class TestTheLatestRunsOfEachPipelineAreKept:
    """R16.2 — the latest N of each pipeline and every pinned run kept; every other deleted."""

    def test_the_five_latest_are_kept_and_the_rest_deleted(self):
        """Row 1 — the one with seven runs and none pinned."""
        kept, deleted = kept_runs(_held(SEVEN))

        assert kept == tuple(SEVEN[2:])
        assert deleted == tuple(SEVEN[:2])

    def test_the_number_kept_is_read(self):
        """Row 2 — the one with `--keep-last 1`: the number is read, not fixed at five."""
        kept, deleted = kept_runs(_held(SEVEN), keep_last=1)

        assert kept == (SEVEN[-1],)
        assert deleted == tuple(SEVEN[:-1])

    def test_a_pinned_run_is_kept_however_old(self):
        """Row 3 — the one where the oldest holds `keep`."""
        kept, deleted = kept_runs(_held(SEVEN, pinned={PINNED}))

        assert kept == (PINNED, *SEVEN[2:])
        assert deleted == (SEVEN[1],)

    def test_each_pipeline_keeps_its_own(self):
        """Row 4 — the one with six runs of one pipeline and two of another."""
        six = SEVEN[1:]
        two = ["20260905T120000Z-aaaa", "20260906T120000Z-bbbb"]

        kept, deleted = kept_runs(_held(six) + _held(two, pipeline="postmortem-review"))

        assert deleted == (six[0],)
        assert set(two) <= set(kept)

    def test_a_pipeline_with_fewer_runs_than_n_loses_none(self):
        """Row 5, counter-example — the one with three runs."""
        kept, deleted = kept_runs(_held(SEVEN[:3]))

        assert kept == tuple(SEVEN[:3])
        assert deleted == ()

    def test_a_directory_with_no_manifest_is_not_a_run(self, tmp_path: Path):
        """Row 6, counter-example — the one `gc` cannot account for, and leaves."""
        _execute(tmp_path, PINNED)
        (tmp_path / "runs" / PINNED / "keep").write_text("", encoding="utf-8")
        (tmp_path / "runs" / "notes-from-the-review").mkdir()

        assert held_runs(tmp_path / "runs") == [
            HeldRun(run_id=PINNED, pipeline="incident-audit", pinned=True)
        ]


def _execute(workspace: Path, run_id: str) -> None:
    """A real run of one document, so `runs/<run_id>/manifest.json` is one `dossier` wrote."""
    from dossier.infrastructure.cache import ArtifactCache

    step = StepConfig(
        id="extract",
        prompt="prompts/extract.md",
        input="documents",
        mode="per_file",
        output="schemas/incident.yaml",
    )
    text = {"INC-4821": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n"}
    execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["incidents-jira"],
                model="anthropic:claude-sonnet-4-5-20250929",
                steps=[step],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="6e0d4b27" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={key: sha256(key.encode()).hexdigest() for key in text},
            document_text=text,
            document_content={"markdown": text},
        ),
        workspace=workspace,
        model=FakeModelClient(responses=['{"document": "INC-4821", "fields": []}']),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )
