"""R4.19 — a `--doc` naming a document no source of the pipeline holds stops
before any call, naming it.

A key mistyped would otherwise be a try about nothing, printed as a success.
Every key is checked before anything is asked: a try that asked about the keys
it could find would look like the try that was meant.

Through the CLI, because `--doc` is read there. The incidents are markdown in a
folder source, so their keys carry the extension (`INC-4821.md`), as R3.17's
do. The model is a fake that **counts calls**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

PIPELINE = "incident-audit"
INCIDENTS = {
    "INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822.md": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call with nothing extracted, and remembers each prompt."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        (document,) = SHOWN.findall(prompt)
        return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


def _try(workspace: Path, monkeypatch, *documents: str) -> tuple[Model, object]:
    """Sync the two incidents, then `dossier run --doc` each of `documents`."""
    import dossier.cli.bootstrap as cli

    for name, text in INCIDENTS.items():
        path = workspace / "inbox" / "tickets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: tickets\n    type: folder\n    path: inbox/tickets/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=["tickets"])
    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    named = [argument for document in documents for argument in ("--doc", document)]
    return model, _cli(workspace, monkeypatch, "run", PIPELINE, *named)


class TestADocumentNoSourceHoldsStopsATry:
    """R4.19 — a `--doc` no source holds stops the try before any call, naming it."""

    def test_a_mistyped_key_is_named_and_nothing_is_asked(self, workspace: Path, monkeypatch):
        """Row 1 — the one where `INC-4899` is held by none of the sources."""
        model, result = _try(workspace, monkeypatch, "INC-4899")

        assert result.exit_code == 2, result.output
        assert (
            f"{PIPELINE}: INC-4899 is held by none of its sources (tickets)" in result.output
        ), result.output
        assert model.prompts == []

    def test_a_held_key_beside_it_is_not_asked_either(self, workspace: Path, monkeypatch):
        """Row 2 — the one where one of the two keys is real, and the try still stops."""
        model, result = _try(workspace, monkeypatch, "INC-4821.md", "INC-4899")

        assert result.exit_code == 2, result.output
        assert "INC-4899 is held by none of its sources" in result.output, result.output
        assert model.prompts == []

    def test_a_held_key_is_tried(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one where the key is spelled as the source holds it."""
        model, result = _try(workspace, monkeypatch, "INC-4821.md")

        assert result.exit_code == 0, result.output
        assert [SHOWN.findall(prompt) for prompt in model.prompts] == [["INC-4821.md"]]
