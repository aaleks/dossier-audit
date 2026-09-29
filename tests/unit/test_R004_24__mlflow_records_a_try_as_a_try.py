"""R4.24 — MLflow records a try as it records a run, tagged a try, and links it
to no version as having produced it.

Every model call a try makes is traced as a run's are (spec 011). The MLflow
run is tagged `dossier.try` with the named documents, sorted and joined by
`, `, so tries are one filter away. A try did not produce the pipeline
version's results, so it is not linked to the version as a record that
produced them (R13.2): a version's page lists only full runs.

Run through `execute` with a `FakeTracker`, which keeps every run, trace and
span it is told about, and a `FakeVersionRegistry`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient, FakeTracker, FakeVersionRegistry
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, RunRecording, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig

EXPERIMENT = "dossier-audit/incident-audit/run"
TRY_TAG = "dossier.try"


def _execute(
    workspace: Path, *, tried: tuple[str, ...] | None
) -> tuple[FakeTracker, FakeVersionRegistry]:
    """`extract` per_file over the four incidents, recorded to MLflow."""
    from dossier.infrastructure.cache import ArtifactCache

    tracker, versions = FakeTracker(), FakeVersionRegistry()
    execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["incidents-jira"],
                model="anthropic:claude-sonnet-4-5-20250929",
                steps=[
                    StepConfig(
                        id="extract",
                        prompt="prompts/extract.md",
                        input="documents",
                        mode="per_file",
                    )
                ],
            ),
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={key: sha256(text.encode()).hexdigest() for key, text in ISSUES.items()},
            document_text=ISSUES,
        ),
        workspace=workspace,
        model=FakeModelClient(
            responses=[json.dumps({"document": key, "fields": []}) for key in sorted(ISSUES)]
        ),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260929T100000Z-1a2b",
        started_at=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
        dossier_version="0.1.0",
        recording=RunRecording(
            tracker=tracker,
            experiment=EXPERIMENT,
            versions=versions,
            version_experiment=EXPERIMENT,
        ),
        tried=tried,
    )
    return tracker, versions


class TestMlflowRecordsATryAsATry:
    """R4.24 — a try is recorded as a run is, tagged a try, and produces no version."""

    def test_a_try_is_one_run_tagged_with_its_documents(self, tmp_path: Path):
        """Row 1 — the one where two tries' documents are one filter away.

        Named out of order on the command line, and tagged sorted: one set of
        documents is one tag value, however it was typed.
        """
        tracker, _ = _execute(tmp_path, tried=("INC-4822", "INC-4821"))

        (run,) = tracker.runs
        assert run.experiment == EXPERIMENT
        assert run.tags[TRY_TAG] == "INC-4821, INC-4822"
        assert [trace.name for trace in run.traces] == [
            "extract · INC-4821",
            "extract · INC-4822",
        ]
        assert [span["kind"] for span in tracker.spans].count("llm") == 2

    def test_a_try_produced_no_version(self, tmp_path: Path):
        """Row 2 — the one where the version's page lists no try among what produced it."""
        tracker, _ = _execute(tmp_path, tried=("INC-4821", "INC-4822"))

        (run,) = tracker.runs
        assert run.produced == []

    def test_a_full_run_is_untagged_and_produced_its_version(self, tmp_path: Path):
        """Row 3, counter-example — the one with no `--doc`: the record R13.2 always made."""
        tracker, versions = _execute(tmp_path, tried=None)

        (run,) = tracker.runs
        assert TRY_TAG not in run.tags
        assert run.produced == [versions.versions[0].version_id]
