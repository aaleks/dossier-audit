"""R12.1 — a gold set publishes as one dataset named after it, one record per document.

The outer loop for spec 012. What a person observes is a command they can run
against a gold set they already have, before any run exists to score: publishing
answers is not scoring a model, and needs neither a sync nor a model call.

The gold set is the person-written one the `workspace` fixture copies from
`tests/fixtures/gold/incidents/` — four documents, `INC-4821`, `INC-4822`,
`INC-4901` and `INC-5455`, with `a.aleks` behind every answer. No gold value in
this file was invented by it.

Tracking is switched on the way a person switches it on, in the environment
(R10.1), and the `{gold}` experiment template is the one `.env.example` ships for
an eval (R10.2 row 2) — so the dataset lands beside the runs measured against it,
which is the address R12.1 row 1 names.

The registry is handed in through the same seam `build_tracker` and
`build_model_client` use. It counts, because R12.1 is a claim about *how many*
datasets and records exist afterwards, not about what came back from making them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.fakes import FakeDatasetRegistry
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
URI = "http://localhost:5000"
EXPERIMENT = "dossier-audit/incident-audit/eval/incidents"
DOCUMENTS = ("INC-4821", "INC-4822", "INC-4901", "INC-5455")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def registry(workspace: Path, monkeypatch) -> FakeDatasetRegistry:
    """Tracking on, the eval template rendering `{gold}`, and a registry that counts."""
    import dossier.cli.bootstrap as cli

    holder = FakeDatasetRegistry()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setenv("DOSSIER_MLFLOW_EXPERIMENT_EVAL", "dossier-audit/{pipeline}/eval/{gold}")
    monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: holder, raising=False)
    write_pipeline(workspace, sources=["incidents-jira"])
    return holder


class TestAGoldSetPublishesAsOneDataset:
    """R12.1 — a gold set publishes as one dataset named after it, one record per document."""

    def test_four_verified_documents_publish_as_one_dataset_of_four_records(
        self, workspace: Path, monkeypatch, registry: FakeDatasetRegistry
    ):
        """Example 1: the one where the four verified documents become four records.

        One dataset, named after the gold directory rather than after the
        pipeline, in the experiment the eval for this gold set records to. Four
        records, one per document — the unit every cache key, trace and score in
        `dossier` is already keyed on.
        """
        result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert list(registry.datasets) == ["incidents"], "one dataset, named after the gold set"
        published = registry.datasets["incidents"]
        assert published.experiments == [EXPERIMENT]
        assert len(published.records) == 4
        documents = sorted(
            record["inputs"]["document"] for record in published.records.values()
        )
        assert documents == sorted(DOCUMENTS)

    def test_the_dataset_is_tagged_with_the_gold_hash_and_its_reviewer(
        self, workspace: Path, monkeypatch, registry: FakeDatasetRegistry
    ):
        """Example 1, second half: the one a person reads back to ask which answers these were.

        The full 64-character hash (R0.7), so two gold sets differing by one
        answer are told apart, and the reviewer behind them — the attribution
        that makes a score answerable at all (R7.7).
        """
        result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        tags = registry.datasets["incidents"].tags
        assert re.fullmatch(r"[0-9a-f]{64}", tags["dossier.gold_hash"])
        assert tags["dossier.verified_by"] == "a.aleks"

    def test_the_terminal_names_the_dataset_its_records_and_its_digest(
        self, workspace: Path, monkeypatch, registry: FakeDatasetRegistry
    ):
        """Example 2: the one where a person can see what was published without opening MLflow.

        The name, the count and the digest, and the experiment it landed in. The
        digest is MLflow's own over the records, not the gold hash the dataset is
        tagged with — the two move together and are different values.
        """
        result = _cli(workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert "incidents" in result.output
        assert "4 records" in result.output
        assert registry.datasets["incidents"].digest in result.output
        assert EXPERIMENT in result.output

    def test_a_gold_directory_holding_no_answers_publishes_nothing(
        self, workspace: Path, monkeypatch, registry: FakeDatasetRegistry
    ):
        """Counter-example (row 3): the one where there is nothing to publish.

        A dataset of no records would read in the UI as a gold set nobody has
        filled in yet, which is what the empty directory already says — and a
        later publish could not tell that dataset from one whose answers were
        deleted. Refused, with nothing sent.
        """
        (workspace / "gold" / "empty").mkdir(parents=True, exist_ok=True)

        result = _cli(
            workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", "gold/empty"
        )

        assert result.exit_code == 2, result.output
        assert "gold/empty" in result.output
        assert registry.datasets == {}, "nothing created"
        assert registry.publishes == [], "nothing sent"
