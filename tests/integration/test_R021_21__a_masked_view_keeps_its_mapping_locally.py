"""R21.21 — a masked view keeps its document's mapping from placeholder to value, on
this machine only.

A gold value or a calibration candidate is masked with its document's
numbering (R21.22), so the document's mapping has to be at hand when the view
is. It is kept beside the view in the cache, in a namespace of its own,
`mask-values`, under the view's `K_mask`: local, with the same exposure as the
snapshots. It is never written where a person shares things -- `runs/`, the
manifest, a provenance record, MLflow -- and the provenance record of the view
still names no value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.fakes import CANARIES, FakeMasker, FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, IssueTracker, abstains

PLAY_6001 = (
    "# PLAY-6001\n\nHans Muster reported that the export never ran.\n"
    "Erika Mustermann holds account CH93 0076 2011 6238 5295 7.\n"
)
INC_4821 = "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n"
MASKING = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)
SHOWN = re.compile(r'<document key="([^"]+)">')


def _masking():
    from dossier.domain.masking import Masking, MaskingDeclaration

    declaration = MaskingDeclaration(
        masker="presidio",
        languages=["en"],
        score_threshold=0.5,
        entities=["PERSON", "IBAN_CODE"],
    )
    return Masking(declaration=declaration, declaration_hash="0" * 64)


def _mask(workspace: Path, texts: dict[str, str], masker: FakeMasker):
    from dossier.application.masking import MASK, mask_texts
    from dossier.infrastructure.cache import ArtifactCache

    return mask_texts(
        texts,
        masking=_masking(),
        masker=masker,
        cache=ArtifactCache(workspace, namespace=MASK),
        values=ArtifactCache(workspace, namespace="mask-values"),
        run_id="20261003T120000Z-0001",
        dossier_version="test",
    )


class Model:
    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        (key,) = SHOWN.findall(prompt)
        return json.dumps({"document": key, "fields": [abstains(f) for f in FIELDS]})


class TestAMaskedViewKeepsItsMappingLocally:
    """R21.21 — the mapping beside the view, in `mask-values`, and nowhere else."""

    def test_the_mapping_is_kept_under_the_views_key(self, workspace: Path):
        """Row 1: the one where `PLAY-6001` is masked."""
        from dossier.infrastructure.cache import ArtifactCache

        result = _mask(workspace, {"PLAY-6001": PLAY_6001}, FakeMasker())

        assert result.mappings["PLAY-6001"] == {
            "[PERSON_1]": "Hans Muster",
            "[PERSON_2]": "Erika Mustermann",
            "[IBAN_CODE_1]": "CH93 0076 2011 6238 5295 7",
        }
        values = ArtifactCache(workspace, namespace="mask-values")
        kept = [json.loads(values.get(key) or b"{}") for key in values.all_keys()]
        assert result.mappings["PLAY-6001"] in kept

    def test_a_view_served_from_the_cache_is_served_with_its_mapping(self, workspace: Path):
        """Row 2: the one where the masker is not asked again."""
        _mask(workspace, {"PLAY-6001": PLAY_6001}, FakeMasker())
        masker = FakeMasker()

        result = _mask(workspace, {"PLAY-6001": PLAY_6001}, masker)

        assert result.mappings["PLAY-6001"]["[PERSON_2]"] == "Erika Mustermann"
        assert masker.call_count == 0

    def test_no_run_output_record_or_span_holds_a_value(self, workspace: Path, monkeypatch):
        """Row 3: the one where a masked run is made and recorded, and the values stay put.

        Searched: everything under `runs/`, every provenance record of the
        masked views, every stage artifact, and every span recorded.
        """
        from typer.testing import CliRunner

        import dossier.cli.bootstrap as cli
        from dossier.cli.main import app

        (workspace / "sources.yaml").write_text(
            "sources:\n  - id: incidents-jira\n    type: issue-tracker\n", encoding="utf-8"
        )
        path = write_pipeline(workspace, sources=["incidents-jira"])
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
        register_connector(
            monkeypatch,
            "issue-tracker",
            lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
        )
        tracker = FakeTracker()
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
        monkeypatch.setattr(
            cli, "build_masker", lambda declaration: FakeMasker(), raising=False
        )
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
        monkeypatch.chdir(workspace)
        runner = CliRunner()
        assert runner.invoke(app, ["sync", "incident-audit"]).exit_code == 0

        result = runner.invoke(app, ["run", "incident-audit"])

        assert result.exit_code == 0, result.output
        shared = [
            *(workspace / "runs").rglob("*"),
            *(workspace / ".dossier" / "cache" / "mask").rglob("*.meta.json"),
            *(workspace / ".dossier" / "cache" / "stage").rglob("*"),
        ]
        written = " ".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in shared
            if path.is_file()
        )
        written += repr(tracker.runs) + repr(tracker.runless_traces)
        assert [value for value in CANARIES if value in written] == []
        assert list((workspace / ".dossier" / "cache" / "mask-values").rglob("*")), "kept"

    def test_a_document_with_nothing_detected_has_an_empty_mapping(self, workspace: Path):
        """Row 4, a counter-example: the one where `INC-4821` names no client."""
        result = _mask(workspace, {"INC-4821": INC_4821}, FakeMasker())

        assert result.mappings["INC-4821"] == {}
