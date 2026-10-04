"""R21.24 — a masked pipeline's gold set is published to MLflow with each
expectation masked by its document's numbering.

`dossier dataset publish` sends a gold set's verified answers to the MLflow
server as a dataset's expectations (spec 012). A person wrote them against the
original document, so they name the client. A masked pipeline's are masked by
the document's own numbering first (R21.22) -- `Erika Mustermann` is
`[PERSON_2]` in the expectation as in the run's answer eval compares it with
(R21.23) -- and an enum, a number or a date is sent as written.

`PLAY-6001` names `Hans Muster` first, so `Erika Mustermann` is `[PERSON_2]`.
The registry is a fake that holds what it was told; the masker finds the
canaries by their exact text.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import CANARIES, FakeDatasetRegistry, FakeMasker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import IssueTracker

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
GOLD = "gold/masked"
PLAY_6001 = (
    "# PLAY-6001\n\n"
    "Hans Muster opened the ticket.\n"
    "Erika Mustermann's settlement was held for two days.\n"
    "Severity was assessed as major.\n"
)
MASKING = "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON]\n"


class Refusing(FakeMasker):
    """The canary masker, failing on `PLAY-6001`'s text."""

    def detect(self, text: str, *, language: str) -> list:
        if "settlement was held for two days" in text:
            raise RuntimeError("the analyzer gave up on this text")
        return super().detect(text, language=language)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _published(workspace: Path, monkeypatch, *, masked: bool = True, masker=None):
    """`PLAY-6001` synced, its gold written, and the gold set published; result and registry."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, name=PIPELINE, sources=[SOURCE_ID])
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    gold = workspace / GOLD
    gold.mkdir(parents=True)
    (gold / "PLAY-6001.json").write_text(
        json.dumps(
            {
                "document": "PLAY-6001",
                "verified_by": "a.aleks",
                "verified_at": "2026-10-04",
                "fields": {
                    "affected_systems": {"value": "Erika Mustermann's settlement was held"},
                    "severity": {"value": "major"},
                },
            }
        ),
        encoding="utf-8",
    )
    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
    )
    registry = FakeDatasetRegistry()
    monkeypatch.setattr(
        cli, "build_masker", lambda declaration: masker or FakeMasker(), raising=False
    )
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setattr(cli, "build_dataset_registry", lambda settings: registry, raising=False)
    return _cli(
        workspace, monkeypatch, "dataset", "publish", PIPELINE, "--gold", GOLD
    ), registry


def _expectations(registry: FakeDatasetRegistry) -> dict:
    ((dataset),) = registry.datasets.values()
    ((record),) = dataset.records.values()
    return record["expectations"]


class TestAMaskedGoldSetPublishesMaskedExpectations:
    """R21.24 — expectations masked by the document's numbering; categories as written."""

    def test_an_expectation_naming_the_client_is_published_masked(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where the gold value names Erika Mustermann."""
        result, registry = _published(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _expectations(registry)["affected_systems"] == "[PERSON_2]'s settlement was held"
        sent = repr(registry.datasets)
        assert [value for value in CANARIES if value in sent] == []

    def test_an_enum_is_published_as_written(self, workspace: Path, monkeypatch):
        """Row 2: the one where an enum's value is never client data."""
        result, registry = _published(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _expectations(registry)["severity"] == "major"

    def test_a_document_that_cannot_be_masked_publishes_nothing(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the masker cannot mask `PLAY-6001`."""
        result, registry = _published(workspace, monkeypatch, masker=Refusing())

        assert result.exit_code == 2, result.output
        assert "PLAY-6001" in result.output
        assert registry.datasets == {}

    def test_an_unmasked_pipelines_gold_is_published_as_written(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where nothing is declared, as R12.2 says."""
        result, registry = _published(workspace, monkeypatch, masked=False)

        assert result.exit_code == 0, result.output
        assert (
            _expectations(registry)["affected_systems"]
            == "Erika Mustermann's settlement was held"
        )
