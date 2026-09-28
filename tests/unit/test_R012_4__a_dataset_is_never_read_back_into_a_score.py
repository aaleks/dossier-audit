"""R012.4 — a dataset is a projection of `gold/`, and no score, key or file is
ever computed from it.

The one-way promise spec 012 opens with, and the reason a dataset is safe to have
at all. R10.4 makes the same promise for tracking as a whole; it is restated for
datasets because a dataset looks far more like an input than a metric does — it
holds the expected answers, which is exactly what a scorer needs, and reading them
from a server instead of from `gold/` would make a score depend on what someone
last published.

Each test makes the dataset and `gold/` disagree, and then asks what the score
followed. A published dataset is left holding the answers as they were while the
files move underneath it -- or the files are deleted and only the dataset is left
-- so a score computed from the dataset would be visibly different from one
computed from the files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import FakeDatasetRegistry, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

GOLD = "gold/incidents"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """The four documents synced and run, with tracking off throughout."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output

    gold = workspace / "gold" / "incidents"
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "calibrations").mkdir(exist_ok=True)
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": RoutedModel.model_id,
                "rubric_hash": text_hash(
                    workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
                ),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


class TestADatasetIsNeverReadBackIntoAScore:
    """R12.4 — a dataset is a projection of `gold/`; no score, key or file comes from it."""

    def test_an_edited_gold_file_is_scored_and_the_stale_dataset_is_not(
        self, audited: Path, monkeypatch
    ):
        """Example 1: the one where `gold/` and the dataset disagree.

        The file is edited after publishing, so the dataset holds the old answer
        and `gold/` holds the new one. The score follows the file: `severity`
        drops to 75%, which it cannot do if anything consulted the dataset.
        """
        gold = audited / "gold" / "incidents" / "INC-4821.json"
        edited = json.loads(gold.read_text(encoding="utf-8"))
        edited["fields"]["severity"] = {"value": "minor"}
        gold.write_text(json.dumps(edited, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert "severity            75.0%" in result.output, result.output

    def test_a_dataset_cannot_stand_in_for_a_gold_set(self, audited: Path, monkeypatch):
        """Example 2: the one where the dataset is all that is left.

        The answers exist in MLflow and nowhere on disk. An eval refuses rather
        than reading them back, because a gold set is reviewed, versioned and in
        git, and a dataset is a copy someone published.
        """
        import shutil

        import dossier.cli.bootstrap as cli

        registry = FakeDatasetRegistry()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)
        published = _cli(audited, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)
        assert published.exit_code == 0, published.output
        assert registry.datasets["incidents"].records, "the answers are in MLflow"

        shutil.rmtree(audited / "gold" / "incidents")

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code != 0, result.output

    def test_nothing_on_disk_holds_the_dataset_id(self, audited: Path, monkeypatch):
        """Example 3: the one where the id MLflow assigned stays out of the workspace.

        The id may reach a tag and the terminal line. A file under `runs/` or
        `.dossier/` holding it would make a cache entry or a manifest depend on
        what a server said, which is what R10.4 row 2 forbids for a run id and
        this forbids for a dataset id.
        """
        import dossier.cli.bootstrap as cli

        registry = FakeDatasetRegistry()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)

        result = _cli(audited, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        dataset_id = registry.find("incidents").dataset_id
        assert dataset_id in result.output, "the terminal may name it"
        written = [
            path
            for directory in ("runs", ".dossier")
            for path in (audited / directory).rglob("*")
            if path.is_file() and dataset_id.encode("utf-8") in path.read_bytes()
        ]
        assert written == [], "no file holds the dataset id"

    def test_publishing_changes_no_score_and_no_key(self, audited: Path, monkeypatch):
        """Counter-example (row 4): the one where publishing did not happen at all.

        The same eval with tracking off scores identically, so publishing and
        linking are observation and not input (R10.4 row 1).
        """
        import dossier.cli.bootstrap as cli

        registry = FakeDatasetRegistry()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: _Silent(), raising=False)
        with_dataset = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        monkeypatch.delenv("DOSSIER_MLFLOW_ENABLED")
        monkeypatch.delenv("DOSSIER_MLFLOW_TRACKING_URI")
        without = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert with_dataset.exit_code == without.exit_code == 0
        scores = [line for line in with_dataset.output.splitlines() if "%" in line]
        assert scores == [line for line in without.output.splitlines() if "%" in line]


class _Silent:
    """A tracker that accepts everything and records nothing.

    Not `FakeTracker`: this test is about the scores being identical, and what was
    recorded is R11.3's claim rather than this one's.
    """

    def __getattr__(self, _name: str):
        return lambda *args, **kwargs: None
