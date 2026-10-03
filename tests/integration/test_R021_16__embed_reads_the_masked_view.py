"""R21.16 — `embed` cuts a masked index's body chunks from each document's masked
view, and a document that cannot be masked is not written.

`dossier embed` was the second road out: it cut its chunks from the converted
text, so a masked pipeline's index held what its runs never showed a model.
Here it reads the masked view, from the cache when a run made it, masking it
itself when none did. The embedding model, the index and the masker are fakes,
reached through the seams `dossier.cli.bootstrap` builds them with; the masker
finds the canaries by their exact text and counts its calls.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.fakes import (
    CANARIES,
    FakeEmbeddingProvider,
    FakeIndexSink,
    FakeMasker,
    register_connector,
)
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, IssueTracker, abstains

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
INDEX = "incidents"
DSN_ENV = "DOSSIER_INDEX_DSN"
EMBEDDING_MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
INDEX_DECLARATION = f"""\
pipeline: {PIPELINE}
embedding_model: {EMBEDDING_MODEL}
chunker: {{name: headings, max_chars: 2000}}
target: {{dsn_env: {DSN_ENV}}}
"""
MASKING = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)
PLAY_6001 = (
    "# PLAY-6001\n\n## Report\n\nErika Mustermann holds account CH93 0076 2011 6238 5295 7.\n"
)
PLAY_6002 = "# PLAY-6002\n\n## Bericht\n\nHans Muster meldete den Ausfall. Er war verärgert.\n"
PLAY_6005 = "# PLAY-6005\n\n## Report\n\nHans Muster asked to be called back.\n"
INC_4821 = "# INC-4821\n\n## Report\n\nFinance confirmed a total exposure CHF 48'200.\n"
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Abstains on every field of the one document a call is about."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        (key,) = SHOWN.findall(prompt)
        return json.dumps({"document": key, "fields": [abstains(f) for f in FIELDS]})


class RaisingOn(FakeMasker):
    """The canary masker, failing on any text that holds `trigger`."""

    def __init__(self, trigger: str) -> None:
        super().__init__()
        self.trigger = trigger

    def detect(self, text: str, *, language: str) -> list:
        if self.trigger in text:
            raise RuntimeError("the analyzer gave up on this text")
        return super().detect(text, language=language)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _workspace(workspace: Path, monkeypatch, issues: dict[str, str], masker: FakeMasker):
    """A masked pipeline over `issues`, synced; its index declared; every fake served."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
        "    acl: [incident-response]\n",
        encoding="utf-8",
    )
    path = write_pipeline(workspace, name=PIPELINE, sources=[SOURCE_ID])
    with path.open("a", encoding="utf-8") as pipeline:
        pipeline.write("masking: masking/cid.yaml\n")
    (path.parent / "masking").mkdir()
    (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    (workspace / "indexes").mkdir()
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(INDEX_DECLARATION, encoding="utf-8")
    tracker = IssueTracker(issues)
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: tracker)
    embedder, sink = FakeEmbeddingProvider(), FakeIndexSink()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
    monkeypatch.setattr(cli, "build_masker", lambda declaration: masker, raising=False)
    monkeypatch.setattr(cli, "build_embedding_provider", lambda model_id: embedder)
    monkeypatch.setattr(cli, "build_index_sink", lambda dsn: sink)
    monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5433/dossier")
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return tracker, embedder, sink


def _texts(sink: FakeIndexSink, key: str) -> str:
    """Everything the index was handed for `key`: its row and its chunks, as one string."""
    held = [
        repr(document) + repr(sink.chunks[(index, document_id)])
        for (index, document_id), document in sink.documents.items()
        if document_id.endswith(f":{key}")
    ]
    return "\n".join(held)


def _asked_about(masker: FakeMasker, marker: str) -> int:
    return sum(marker in call["text"] for call in masker.calls)


class TestEmbedReadsTheMaskedView:
    """R21.16 — the masked view, from the run or masked by embed; never the converted text."""

    def test_the_runs_masked_view_is_read_from_the_cache(self, workspace: Path, monkeypatch):
        """Row 1: the one where the run masked `PLAY-6001` before."""
        masker = FakeMasker()
        _, embedder, sink = _workspace(workspace, monkeypatch, {"PLAY-6001": PLAY_6001}, masker)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        asked = _asked_about(masker, "# PLAY-6001")

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        held = _texts(sink, "PLAY-6001")
        assert "[PERSON_1]" in held and "[IBAN_CODE_1]" in held
        assert [value for value in CANARIES if value in held + " ".join(embedder.texts)] == []
        assert _asked_about(masker, "# PLAY-6001") == asked, "served from the cache"

    def test_a_document_no_run_masked_is_masked_by_embed(self, workspace: Path, monkeypatch):
        """Row 2: the one where `PLAY-6005` was synced after the run."""
        masker = FakeMasker()
        tracker, _, sink = _workspace(workspace, monkeypatch, {"PLAY-6001": PLAY_6001}, masker)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        tracker.issues["PLAY-6005"] = PLAY_6005
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert "[PERSON_1] asked to be called back" in _texts(sink, "PLAY-6005")
        assert _asked_about(masker, "# PLAY-6005") == 1

    def test_a_document_the_masker_fails_on_is_not_written(self, workspace: Path, monkeypatch):
        """Row 3: the one where the masker raises on `PLAY-6002`."""
        issues = {"PLAY-6001": PLAY_6001, "PLAY-6002": PLAY_6002}
        _, embedder, sink = _workspace(workspace, monkeypatch, issues, RaisingOn("verärgert"))

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert "PLAY-6002: not masked, its rows are kept: masking failed:" in result.output
        assert _texts(sink, "PLAY-6002") == ""
        assert "[PERSON_1]" in _texts(sink, "PLAY-6001")
        assert all("Hans Muster" not in text for text in embedder.texts)

    def test_a_key_that_names_a_client_is_not_written(self, workspace: Path, monkeypatch):
        """Row 4: the one where a document's key names the client."""
        issues = {"PLAY-6001": PLAY_6001, "Erika-Mustermann-complaint": INC_4821}
        _, embedder, sink = _workspace(workspace, monkeypatch, issues, FakeMasker())

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert "Erika-Mustermann-complaint: not masked, its rows are kept" in result.output
        assert not any("Erika-Mustermann" in document_id for _, document_id in sink.documents)
        assert all("Erika" not in text for text in embedder.texts)

    def test_a_document_with_nothing_detected_is_written_as_converted(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, a counter-example: the one where `INC-4821` names no client."""
        _, _, sink = _workspace(workspace, monkeypatch, {"INC-4821": INC_4821}, FakeMasker())

        result = _cli(workspace, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert "Finance confirmed a total exposure CHF 48'200." in _texts(sink, "INC-4821")
