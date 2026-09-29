"""R4.26 — `dossier run` given two of `--plan`, `--replay` and `--doc` stops
before anything is read, naming both.

Each makes `dossier run` a different command: a plan of a full run (R4.6), the
reproduction of a past one (R4.7), or a try (R4.18). Until this rule, the pair
ran one and ignored the other, and printed a success for a command nobody
typed.

Through the CLI, because flags are read there. A full run is made first, so a
replay has a real run to be refused against, and `replays/` under it is a
directory that could have been written. The incidents are markdown in a folder
source, so their keys carry the extension (`INC-4821.md`), as R3.17's do.
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
    """Answers every call with nothing extracted, and keeps each prompt."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        (document,) = SHOWN.findall(prompt)
        return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


def _ran(workspace: Path, monkeypatch) -> tuple[Model, str]:
    """The two incidents synced and run in full; the model and the run's directory."""
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
    assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
    (run_id,) = sorted(path.name for path in (workspace / "runs").iterdir())
    model.prompts.clear()
    return model, f"runs/{run_id}/"


class TestTwoModesOfRunAreRefused:
    """R4.26 — two of `--plan`, `--replay` and `--doc` stop `dossier run`, naming both."""

    def test_a_try_is_not_planned(self, workspace: Path, monkeypatch):
        """Row 1 — the one where a plan is asked of a try."""
        model, _ = _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan", "--doc", "INC-4821.md")

        assert result.exit_code == 2, result.output
        assert (
            "--doc cannot be combined with --plan: a plan compares a full run with the last one"
            in result.output
        ), result.output
        assert "compared against" not in result.output, "a plan was printed"
        assert model.prompts == []

    def test_a_try_is_not_replayed(self, workspace: Path, monkeypatch):
        """Row 2 — the one where a replay is asked of a try."""
        model, run = _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", "--replay", run, "--doc", "INC-4821.md")

        assert result.exit_code == 2, result.output
        assert (
            "--doc cannot be combined with --replay: a replay reproduces a whole run"
            in result.output
        ), result.output
        assert not (workspace / run / "replays").exists(), "a replay was written"
        assert model.prompts == []

    def test_a_replay_is_not_planned(self, workspace: Path, monkeypatch):
        """Row 3 — the one where a plan and a replay are asked at once."""
        model, run = _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan", "--replay", run)

        assert result.exit_code == 2, result.output
        assert (
            "--plan cannot be combined with --replay: a replay reproduces a past run "
            "and plans nothing" in result.output
        ), result.output
        assert not (workspace / run / "replays").exists(), "a replay was written"
        assert model.prompts == []

    def test_a_try_alone_is_a_try(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one where `--doc` stands alone."""
        model, _ = _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--doc", "INC-4821.md")

        assert result.exit_code == 0, result.output
        assert result.output.startswith("try "), result.output
        assert "extract: 1 document(s) · 1 from cache" in result.output, result.output
        assert model.prompts == [], "served the full run's answer (R4.21)"
