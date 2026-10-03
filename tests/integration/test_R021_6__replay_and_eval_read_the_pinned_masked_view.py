"""R21.6 — a masked run's manifest pins its masker, and a replay and an eval read
the masked view through it.

`replayed_inputs` is the second road to a model: `eval` shows its judge the
text a run read through it, and `--replay` recomposes every stage key from it.
Unpinned, both would read the converted text -- the judge shown the client's
name, the replay recomposing keys no masked run ever wrote. Pinned, both read
the masked view the run itself was shown, from the cache, and never ask a
masker: a replay re-masking with today's declaration would reproduce today's
masking, not that run (R4.7).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from tests.fakes import FakeMasker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, IssueTracker, abstains, found

from dossier.domain.hashing import text_hash

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
GOLD = "gold/masked"
CAUSE = "the settlement export was scheduled at a local time that did not exist"
PLAY_6001 = (
    "# PLAY-6001\n\n"
    "Erika Mustermann holds account CH93 0076 2011 6238 5295 7.\n"
    f"Root cause: {CAUSE}.\n"
)
DECLARATION = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)


class Model:
    """Answers the step with the cause, and the judge with a verdict; remembers both."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.judged: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        if schema is not None and "supported" in (schema.get("properties") or {}):
            self.judged.append(prompt)
            return json.dumps({"supported": True, "evidence": "stated"})
        return json.dumps(
            {
                "document": "PLAY-6001",
                "fields": [
                    *(abstains(field) for field in FIELDS if field != "root_cause"),
                    found("PLAY-6001", "root_cause", CAUSE, CAUSE),
                ],
            }
        )


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _gold(workspace: Path) -> None:
    from dossier.application.eval import judge_prompt_hash

    gold = workspace / GOLD
    (gold / "calibrations").mkdir(parents=True)
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "PLAY-6001.json").write_text(
        json.dumps(
            {
                "document": "PLAY-6001",
                "verified_by": "a.aleks",
                "verified_at": "2026-10-02",
                "fields": {"root_cause": {"value": CAUSE}},
            }
        ),
        encoding="utf-8",
    )
    rubric = workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": Model.model_id,
                "rubric_hash": text_hash(rubric),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _ran(workspace: Path, monkeypatch, *, masked: bool = True):
    """`PLAY-6001` synced and run once; the run id, the model and the masker."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, name=PIPELINE, sources=[SOURCE_ID])
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(DECLARATION, encoding="utf-8")
    _gold(workspace)
    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
    )
    model = Model()
    masker = FakeMasker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    monkeypatch.setattr(cli, "build_masker", lambda declaration: masker, raising=False)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    return re.search(r"^run (\S+)", ran.output, re.MULTILINE).group(1), model, masker


class TestReplayAndEvalReadThePinnedMaskedView:
    """R21.6 — the masked view a run was shown, read back through its manifest."""

    def test_the_judge_is_shown_the_masked_text_the_step_was_shown(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where an eval follows a masked run."""
        _, model, masker = _ran(workspace, monkeypatch)
        asked = masker.call_count

        scored = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert scored.exit_code == 0, scored.output
        (judged,) = model.judged
        assert "[PERSON_1]" in judged
        assert "Erika Mustermann" not in judged
        assert masker.call_count == asked, "an eval masks nothing; it reads what the run masked"

    def test_a_replay_reads_the_pinned_view_whatever_the_declaration_says_now(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where `cid.yaml` was edited after the run."""
        run, _, masker = _ran(workspace, monkeypatch)
        declaration = workspace / "pipelines" / PIPELINE / "masking" / "cid.yaml"
        declaration.write_text(DECLARATION.replace("0.5", "0.9"), encoding="utf-8")
        asked = masker.call_count

        replayed = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{run}")

        assert replayed.exit_code == 0, replayed.output
        assert masker.call_count == asked

    def test_a_replay_whose_masked_view_is_gone_stops_naming_it(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the masked view is gone.

        Nothing is substituted: re-masking with today's masker would reproduce
        today's masking, not the run's (R4.7).
        """
        run, _, masker = _ran(workspace, monkeypatch)
        shutil.rmtree(workspace / ".dossier" / "cache" / "mask")
        asked = masker.call_count

        replayed = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{run}")

        assert replayed.exit_code == 2, replayed.output
        assert "PLAY-6001" in replayed.output
        assert "masked view" in replayed.output
        assert masker.call_count == asked

    def test_an_unmasked_run_pins_no_masker(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where nothing is declared.

        Its manifest has no `masker` key at all, so its bytes are what a run
        wrote before this spec (R4.8).
        """
        run, _, _ = _ran(workspace, monkeypatch, masked=False)

        manifest = json.loads((workspace / "runs" / run / "manifest.json").read_text("utf-8"))

        assert "masker" not in manifest["plan"]
