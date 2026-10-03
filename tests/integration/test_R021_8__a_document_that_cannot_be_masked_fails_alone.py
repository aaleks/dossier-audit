"""R21.8 — a document that cannot be masked fails alone, and no model is asked about it.

Fail closed, per document: a masker that fails on one document, or a key that
itself names a client, never means the document is sent unmasked instead. It
is named, the rest of the run goes on, and the command exits 1 -- R8.6's shape,
as a document that did not convert.

Run through the CLI with `FakeMasker`, which finds the canaries by their exact
text, and a model that records every prompt it is sent.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from tests.fakes import FakeMasker
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

PIPELINE = "incident-audit"
POSTMORTEMS = (
    Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
)
SOURCES = """\
sources:
  - id: incidents
    type: folder
    path: inbox/tickets/
  - id: procedures
    type: folder
    path: inbox/procedures/
"""
DECLARATION = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call about the one document its `<source_document>` holds."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        return json.dumps({"document": _about(prompt), "fields": [abstains(f) for f in FIELDS]})

    def asked_about(self) -> list[str]:
        return sorted(_about(prompt) for prompt in self.prompts)


def _about(prompt: str) -> str:
    """The one document a prompt's `<source_document>` holds."""
    held = prompt.split("<source_document>")[1].split("</source_document>")[0]
    return SHOWN.findall(held)[0]


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


def _run(
    workspace: Path,
    monkeypatch,
    *,
    tickets: dict[str, str | Path],
    masker: FakeMasker,
    procedures: dict[str, str] | None = None,
):
    """Sync and run a masked pipeline over `tickets`; the result and the model."""
    import dossier.cli.bootstrap as cli

    for folder, files in (("tickets", tickets), ("procedures", procedures or {})):
        directory = workspace / "inbox" / folder
        directory.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            if isinstance(content, Path):
                shutil.copyfile(content, directory / name)
            else:
                (directory / name).write_text(content, encoding="utf-8")
    (workspace / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    path = write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["incidents"],
        reference=["procedures"] if procedures else None,
        inputs={"extract": "[documents, reference]"} if procedures else None,
    )
    with path.open("a", encoding="utf-8") as pipeline:
        pipeline.write("masking: masking/cid.yaml\n")
    (path.parent / "masking").mkdir()
    (path.parent / "masking" / "cid.yaml").write_text(DECLARATION, encoding="utf-8")

    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    monkeypatch.setattr(cli, "build_masker", lambda declaration: masker, raising=False)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return _cli(workspace, monkeypatch, "run", PIPELINE), model


PLAY_6001 = "# PLAY-6001\n\nHans Muster reported that the settlement export never ran.\n"
PLAY_6002 = "# PLAY-6002\n\nErika Mustermann meldete den Ausfall. Sie war verärgert.\n"


class TestADocumentThatCannotBeMaskedFailsAlone:
    """R21.8 — named, never sent, and the rest of the run goes on."""

    def test_a_document_the_masker_fails_on_is_named_and_the_rest_run(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where the masker raises on `PLAY-6002`."""
        result, model = _run(
            workspace,
            monkeypatch,
            tickets={"PLAY-6001.md": PLAY_6001, "PLAY-6002.md": PLAY_6002},
            masker=RaisingOn("verärgert"),
        )

        assert result.exit_code == 1, result.output
        assert model.asked_about() == ["PLAY-6001.md"]
        assert "PLAY-6002.md could not be masked" in result.stderr
        assert "the analyzer gave up on this text" in result.stderr
        assert all("Erika Mustermann" not in prompt for prompt in model.prompts)

    def test_a_key_that_names_a_client_is_never_sent(self, workspace: Path, monkeypatch):
        """Row 2: the one where the key names the client.

        A key is shown to the model in every `<document key="...">` (R3.13), so
        a file named after a client would carry the name past its own masked
        text. The PDF is one of the corpus's postmortems under that name.

        The masker knows `Erika Mustermann` with a space, as a named-entity
        model does: `en_core_web_lg` finds no person in
        `Erika-Mustermann-complaint.pdf` and finds one in the same name with its
        separators read as spaces (measured 2026-10-03). So a key is read that
        way before it is masked.
        """
        name = "Erika-Mustermann-complaint.pdf"
        masker = FakeMasker()
        pdf = POSTMORTEMS / "INC-5102-orders-api-oom-postmortem.pdf"
        tickets = {"PLAY-6001.md": PLAY_6001, name: pdf}

        result, model = _run(workspace, monkeypatch, tickets=tickets, masker=masker)

        assert result.exit_code == 1, result.output
        assert model.asked_about() == ["PLAY-6001.md"]
        assert f"{name} could not be masked" in result.stderr
        assert all("Erika-Mustermann" not in prompt for prompt in model.prompts)

    def test_a_reference_document_that_cannot_be_masked_is_left_out_of_the_context(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the masker raises on the procedure.

        Left out of every call's context and named, as a reference document
        that did not convert is; the incidents are still asked about.
        """
        procedure = "# OPS-114 Incident escalation procedure\n\nEscalate after 30 Minuten.\n"

        result, model = _run(
            workspace,
            monkeypatch,
            tickets={"PLAY-6001.md": PLAY_6001},
            procedures={"OPS-114.md": procedure},
            masker=RaisingOn("Minuten"),
        )

        assert result.exit_code == 1, result.output
        assert model.asked_about() == ["PLAY-6001.md"]
        assert all("OPS-114" not in prompt for prompt in model.prompts)
        assert "OPS-114.md could not be masked" in result.stderr

    def test_a_document_with_nothing_detected_is_sent_as_converted(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where the masker detects nothing.

        `INC-4821` names no client. Its masked view is its text, it is sent as
        converted, and nothing detected is not a failure.
        """
        clean = "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n"

        result, model = _run(
            workspace, monkeypatch, tickets={"INC-4821.md": clean}, masker=FakeMasker()
        )

        assert result.exit_code == 0, result.output
        assert model.asked_about() == ["INC-4821.md"]
        assert "Finance confirmed a total exposure CHF 48'200." in model.prompts[0]
