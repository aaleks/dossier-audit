"""R21.12 — a `dossier run` of a masked pipeline with the `presidio` masker shows no
model a canary.

The acceptance rule of spec 021's second part, and the one that runs the real
masker: Presidio with spaCy's `lg` models for English, German, French and
Italian, built the way `dossier` builds it -- models loaded by `dossier`, never
fetched; the suffix list `tldextract` ships with, never one from the network.
R21.1 proved the mechanism with a fake that finds the canaries by their exact
text. This proves that the real masker finds them in four languages' prose.

`live`: it needs the four models, which the `masking-models` extra installs and
CI does not. The model the run asks is still a fake that records its prompts:
what is claimed is what was shown to it.

The corpus is `_fixtures.md`'s canary corpus, `PLAY-6001` - `PLAY-6004`, one
note per language with every canary in it.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from tests.fakes import CANARIES
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

pytestmark = pytest.mark.live

PIPELINE = "incident-audit"
CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "cid"
SOURCES = "sources:\n  - id: incidents\n    type: folder\n    path: inbox/tickets/\n"
DECLARATION = r"""masker: presidio
languages: [en, de, fr, it]
score_threshold: 0.5
entities:
  - PERSON
  - EMAIL_ADDRESS
  - PHONE_NUMBER
  - IBAN_CODE
  - CREDIT_CARD
  - CH_AHV
  - CLIENT_NUMBER
patterns:
  CH_AHV: {regex: '\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b', score: 0.5, context: [ahv, avs]}
  CLIENT_NUMBER: {regex: '\bCIF \d{4}-\d{6}\b', score: 0.85}
"""
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Abstains on every field of the one document a call is about; remembers each prompt."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: dict[str, str] = {}

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        (key,) = SHOWN.findall(prompt)
        self.prompts[key] = prompt
        return json.dumps({"document": key, "fields": [abstains(f) for f in FIELDS]})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def ran(workspace: Path, monkeypatch) -> tuple[Path, Model]:
    """The canary corpus, synced and run once through the real masker."""
    import dossier.cli.bootstrap as cli

    tickets = workspace / "inbox" / "tickets"
    tickets.mkdir(parents=True)
    for note in sorted(CORPUS.glob("PLAY-600*.md")):
        shutil.copyfile(note, tickets / note.name)
    (workspace / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    path = write_pipeline(workspace, name=PIPELINE, sources=["incidents"])
    with path.open("a", encoding="utf-8") as pipeline:
        pipeline.write("masking: masking/cid.yaml\n")
    (path.parent / "masking").mkdir()
    (path.parent / "masking" / "cid.yaml").write_text(DECLARATION, encoding="utf-8")

    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return workspace, model


class TestPresidioMasksEveryCanaryBeforeTheModel:
    """R21.12 — the real masker, four languages, and no canary shown to the model."""

    def test_no_prompt_holds_a_canary_and_each_note_is_read_in_its_language(self, ran):
        """Row 1: the one where every canary in four languages is masked."""
        workspace, model = ran

        assert sorted(model.prompts) == [f"PLAY-600{n}.md" for n in (1, 2, 3, 4)]
        held = {
            key: [value for value in CANARIES if value in prompt]
            for key, prompt in model.prompts.items()
        }
        assert held == {key: [] for key in model.prompts}
        records = (workspace / ".dossier" / "cache" / "mask").rglob("*.meta.json")
        languages = {json.loads(record.read_text("utf-8"))["language"] for record in records}
        assert {"en", "de", "fr", "it"} <= languages

    def test_a_german_phone_number_beside_telefon_is_masked(self, ran):
        """Row 2: the one where the German context word lifts a phone number over the bar."""
        _, model = ran

        prompt = model.prompts["PLAY-6002.md"]

        assert "+41 44 555 01 23" not in prompt
        assert "[PHONE_NUMBER_1]" in prompt

    def test_the_client_number_is_masked_by_the_declared_pattern(self, ran):
        """Row 3: the one where Presidio alone does not find the client number."""
        _, model = ran

        assert all("[CLIENT_NUMBER_1]" in prompt for prompt in model.prompts.values())

    def test_an_engineers_username_is_sent_as_written(self, ran):
        """Row 4, a counter-example: the one where what is not declared is not masked.

        `k.oyelaran` is an employee's username, not client data, and no
        declared type finds it.
        """
        _, model = ran

        assert "k.oyelaran" in model.prompts["PLAY-6001.md"]
