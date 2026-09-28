"""R4.16 — a manifest pins the reference documents apart from the audited ones,
and a replay recomposes `{{reference}}` from them.

A call that read `reference` was shown every reference document (R3.18), so a
replay has to show it the same ones: the ones the run read, at the snapshots it
read. Keys cannot say which documents were context, as they can say which were
a group (R4.15), so the manifest says it, under `reference`.

Through the CLI: `dossier run`, then `dossier run --replay`, because the
replay's text is read back by the snapshots the manifest pinned, and a
procedure re-synced since is what it must not see. The documents are markdown
in folder sources, so their keys carry the extension, and the incidents are
kept in `inbox/tickets/` because the workspace fixture fills `inbox/incidents/`.
The model is a fake that counts its calls (R0.1).
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
OPS_114 = "OPS-114.md"
V37 = "# OPS-114 Incident escalation\n\nEscalate within 30 minutes.\n"
V38 = "# OPS-114 Incident escalation\n\nEscalate within 15 minutes.\n"
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call with nothing extracted, and counts them."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.calls += 1
        audited = SHOWN.findall(prompt)
        return json.dumps({"document": audited[0], "fields": [abstains(f) for f in FIELDS]})


def _ran(workspace: Path, monkeypatch) -> tuple[Model, Path]:
    """One run of `extract` then `verify`, which reads the procedure; its run directory."""
    import dossier.cli.bootstrap as cli

    for name, text in INCIDENTS.items():
        path = workspace / "inbox" / "tickets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    procedure = workspace / "inbox" / "procedures" / OPS_114
    procedure.parent.mkdir(parents=True)
    procedure.write_text(V37, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: tickets\n    type: folder\n    path: inbox/tickets/\n"
        "  - id: procedures\n    type: folder\n    path: inbox/procedures/\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["tickets"],
        reference=["procedures"],
        steps=["extract", "verify"],
        inputs={"verify": "[documents, extract, reference]"},
    )
    model = Model()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    (run,) = [path for path in (workspace / "runs").iterdir() if path.is_dir()]
    return model, run


def _replayed(run: Path) -> Path:
    (replayed,) = (run / "replays").iterdir()
    return replayed


class TestAReplayRecomposesReferenceFromItsManifest:
    """R4.16 — the context a run read, pinned and read back."""

    def test_the_manifest_pins_reference_apart(self, workspace: Path, monkeypatch):
        """Row 1: the one where the procedure is pinned as context, not as a document."""
        _, run = _ran(workspace, monkeypatch)

        plan = json.loads((run / "manifest.json").read_text(encoding="utf-8"))["plan"]
        assert [document["key"] for document in plan["documents"]] == list(INCIDENTS)
        assert [document["key"] for document in plan["reference"]] == [OPS_114]

    def test_a_run_that_read_reference_replays_byte_for_byte(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where every answer comes back from the cache the run wrote."""
        model, run = _ran(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", "--replay", str(run))

        assert result.exit_code == 0, result.output
        assert model.calls == 4
        for name in INCIDENTS:
            answer = f"{name}.json"
            assert (_replayed(run) / "verify" / answer).read_bytes() == (
                run / "verify" / answer
            ).read_bytes()

    def test_a_procedure_synced_since_is_not_what_the_replay_reads(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where `OPS-114` moved on after the run.

        The replay reads the snapshot the manifest pinned, so it finds the keys
        the run wrote. Read from what is held now, it would find none.
        """
        _, run = _ran(workspace, monkeypatch)
        (workspace / "inbox" / "procedures" / OPS_114).write_text(V38, encoding="utf-8")
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", "--replay", str(run))

        assert result.exit_code == 0, result.output
        assert "4 artifact(s) reproduced" in result.output

    def test_a_manifest_from_before_the_rule_cannot_be_reproduced(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one written before reference was pinned.

        Read as no reference at all, so `verify`'s keys are recomposed over
        nothing, and are keys no run wrote. The replay stops and names the
        entry rather than substituting anything.
        """
        _, run = _ran(workspace, monkeypatch)
        manifest = run / "manifest.json"
        written = json.loads(manifest.read_text(encoding="utf-8"))
        del written["plan"]["reference"]
        manifest.write_text(json.dumps(written, indent=2), encoding="utf-8")

        result = _cli(workspace, monkeypatch, "run", "--replay", str(run))

        assert result.exit_code == 2, result.output
        assert "cannot be reproduced" in result.output
        assert "verify" in result.output
