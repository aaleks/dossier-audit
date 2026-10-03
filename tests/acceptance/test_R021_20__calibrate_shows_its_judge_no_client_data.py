"""R21.20 — `dossier calibrate` of a masked pipeline shows its judge no value its
masker detects.

Calibration was the last road from a masked pipeline to a model. A judge is
shown each sample case's document and a candidate answer, and the candidates
are written by a person against the original document -- here, every one names
`Erika Mustermann`. So the judge is shown the document's masked view, and each
candidate masked with that document's numbering (R21.22): the client is
`[PERSON_2]` in both, and the judge can still tell whether the one supports the
other.

The model is a fake that records every prompt; the masker finds the canaries
by their exact text; the tracker records what it is told.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import CANARIES, FakeMasker, FakeTracker, register_connector
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
)
CANDIDATE = "Erika Mustermann's settlement was held"
MASKING = "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON]\n"


class Judge:
    """Answers every judge question as supported, and remembers every prompt."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        return json.dumps({"supported": True, "evidence": "stated"})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _calibrated(workspace: Path, monkeypatch, *, masked: bool = True):
    """Twenty cases on `PLAY-6001`, each candidate naming the client; calibrated."""
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
    samples = workspace / GOLD / "samples"
    samples.mkdir(parents=True)
    (workspace / GOLD / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (samples / "root_cause.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "document": "PLAY-6001",
                    "answer": f"{CANDIDATE} ({index})",
                    "supported": True,
                    "verified_by": "a.aleks",
                    "verified_at": "2026-10-03",
                }
            )
            for index in range(20)
        )
        + "\n",
        encoding="utf-8",
    )
    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
    )
    judge, tracker = Judge(), FakeTracker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
    monkeypatch.setattr(cli, "build_masker", lambda declaration: FakeMasker(), raising=False)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
    result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)
    assert result.exit_code == 0, result.output
    return judge, tracker


def _held(text: str) -> list[str]:
    return [value for value in CANARIES if value in text]


class TestCalibrateShowsItsJudgeNoClientData:
    """R21.20 — the masked view, and each candidate masked by its document's numbering."""

    def test_the_judge_is_shown_the_masked_view_and_masked_candidates(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where every candidate names the client."""
        judge, _ = _calibrated(workspace, monkeypatch)

        assert len(judge.prompts) == 20
        assert _held(" ".join(judge.prompts)) == []
        assert all("[PERSON_2]'s settlement was held" in prompt for prompt in judge.prompts)
        assert all("[PERSON_1] opened the ticket" in prompt for prompt in judge.prompts)

    def test_no_span_of_the_calibration_holds_a_canary(self, workspace: Path, monkeypatch):
        """Row 2: the one where the calibration is recorded under `capture: full`."""
        _, tracker = _calibrated(workspace, monkeypatch)

        recorded = repr(tracker.runs) + repr(tracker.runless_traces)

        assert tracker.runs, "the calibration recorded nothing, so the rule is vacuous"
        assert _held(recorded) == []

    def test_an_unmasked_pipelines_judge_is_shown_what_was_written(
        self, workspace: Path, monkeypatch
    ):
        """Row 3, a counter-example: the one where nothing is declared."""
        judge, _ = _calibrated(workspace, monkeypatch, masked=False)

        assert all(CANDIDATE in prompt for prompt in judge.prompts)
        assert all("Hans Muster opened the ticket" in prompt for prompt in judge.prompts)
