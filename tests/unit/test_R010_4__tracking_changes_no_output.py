"""R10.4 — enabling tracking changes no manifest, cache key, artifact or
provenance record.

Tracking observes a run; it is not an input to one (R0.5). If turning it on
moved a single byte a run writes, a run's result would depend on whether a
server happened to be up, and a cache hit would stop meaning that nothing
relevant changed. What a person *reads* may differ -- the command names the
MLflow run it recorded to -- and what is written to disk may not.

Rows 1 and 2 run `execute` directly over the same inputs, with and without a
tracker. Row 3 goes through the CLI, because it is about what the command
prints.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from tests.conftest import FIXTURES
from tests.fakes import FakeModelClient, FakeTracker, register_connector
from tests.pipelines import prompt_for, write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SNAPSHOTS = {
    "INC-4821": "a3f9c1e2" * 8,
    "INC-4822": "77c1b40a" * 8,
    "INC-4901": "0e52dd18" * 8,
    "INC-5455": "c4a70b93" * 8,
}
CONFIG = PipelineConfig(
    name="incident-audit",
    sources=["incidents-jira"],
    model=MODEL,
    steps=[
        StepConfig(
            id="extract",
            prompt="prompts/extract.md",
            input="documents",
            mode="per_file",
            output="schemas/incident.yaml",
        )
    ],
)
# What MLflow would call the run. dossier never learns it: the port returns
# nothing (R0.10), so there is no path by which it could be written down.
MLFLOW_RUN_ID = "3f8e1c2a9b7d4e6f8a1b2c3d4e5f6a7b"


class IdentifiedTracker(FakeTracker):
    """A tracker holding the id its server would assign, as MLflow's does."""

    mlflow_run_id = MLFLOW_RUN_ID


def _answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {"field": "loss_amount", "value": None, "reason": "not stated in document"}
            ],
        }
    )


def _execute(workspace: Path, *, run_id: str, started_at: datetime, tracker=None) -> Path:
    """The same run of `extract` over the four incidents; its manifest's path."""
    report = execute(
        workspace=workspace,
        pipeline=CONFIG,
        pipeline_hash="6e0d4b27" * 8,
        documents=SNAPSHOTS,
        document_text=ISSUES,
        schemas={
            "extract": OutputSchema(schema={"type": "object"}, declaration_hash="d24c86e1" * 8)
        },
        prompts={"extract": prompt_for(["documents"])},
        model=FakeModelClient(responses=[_answer(key) for key in sorted(SNAPSHOTS)]),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=started_at,
        dossier_version="0.1.0",
        tracker=tracker,
        experiment="dossier-audit/incident-audit/run" if tracker is not None else None,
    )
    return report.manifest_path


def _written(workspace: Path) -> list[Path]:
    return sorted(path for path in workspace.rglob("*") if path.is_file())


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


class TestTrackingChangesNoOutput:
    """R10.4 — enabling tracking changes no manifest, cache key, artifact or
    provenance record."""

    def test_the_same_inputs_tracked_and_untracked_write_the_same_run(self, tmp_path: Path):
        """Example 1: the one run with tracking on and with it off.

        The manifests agree byte for byte apart from the run id and the start
        time, which record *when* rather than *what* (R0.4), and the two
        workspaces hold the same cache entries under the same keys.
        """
        untracked, tracked = tmp_path / "off", tmp_path / "on"
        off = _execute(
            untracked,
            run_id="20260806T142203Z-4f1a",
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        )
        on = _execute(
            tracked,
            run_id="20260806T152203Z-4f1a",
            started_at=datetime(2026, 8, 6, 15, 22, 3, tzinfo=UTC),
            tracker=FakeTracker(),
        )

        def what(manifest: Path) -> dict:
            recorded = json.loads(manifest.read_text(encoding="utf-8"))
            return {k: v for k, v in recorded.items() if k not in ("run_id", "started_at")}

        assert what(off) == what(on)
        assert [
            p.relative_to(untracked / ".dossier") for p in _written(untracked / ".dossier")
        ] == [p.relative_to(tracked / ".dossier") for p in _written(tracked / ".dossier")]

    def test_nothing_a_recorded_run_writes_holds_the_mlflow_run_id(self, tmp_path: Path):
        """Example 2: the one recorded to a server that assigned its own run id.

        No file under `runs/` or `.dossier/` holds it. There is nothing to read
        it back through -- the port returns nothing -- so a record in MLflow
        can never become part of what a run wrote.
        """
        _execute(
            tmp_path,
            run_id="20260806T142203Z-4f1a",
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            tracker=IdentifiedTracker(),
        )

        written = _written(tmp_path)
        assert written, "the run wrote nothing, so the search below would prove nothing"
        assert [path for path in written if MLFLOW_RUN_ID.encode() in path.read_bytes()] == []

    def test_what_the_command_prints_gains_one_line_naming_the_mlflow_run(
        self, tmp_path: Path, monkeypatch
    ):
        """Counter-example (row 3): the one read by a person rather than written to disk.

        With tracking on, `dossier run` prints one extra line, naming the MLflow
        run it recorded to. What a person reads may differ; nothing on disk may.
        """
        import dossier.cli.bootstrap as cli

        outputs = {}
        for tracking in ("off", "on"):
            workspace = tmp_path / tracking
            shutil.copytree(FIXTURES, workspace)
            source = IssueTracker(ISSUES)
            (workspace / "sources.yaml").write_text(
                f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
            )
            write_pipeline(workspace, sources=[SOURCE_ID])
            register_connector(
                monkeypatch,
                SOURCE_TYPE,
                lambda config, *, workspace, source=source: source,
            )
            assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

            if tracking == "on":
                monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
                monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
                monkeypatch.setattr(cli, "build_tracker", lambda settings: FakeTracker())
            monkeypatch.setattr(
                cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS)
            )
            result = _cli(workspace, monkeypatch, "run", PIPELINE)
            assert result.exit_code == 0, result.output
            outputs[tracking] = result.output.splitlines()

        extra = [line for line in outputs["on"] if "MLflow" in line]
        assert len(outputs["on"]) == len(outputs["off"]) + 1
        assert len(extra) == 1
        run_id = outputs["on"][0].split()[1]
        assert run_id in extra[0]
