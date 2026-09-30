"""R17.4 — `dossier status PIPELINE --gold DIR` names each judged field with the
reason `dossier eval PIPELINE --gold DIR` would withhold it, or `reportable`.

One decision, asked twice: `status` calls the gate `eval` calls, with the same
judge model and the same grounding states, and prints the reason it returns
unchanged. Two gates written to agree would drift apart the first time one
of them learned a new reason (R7.31 added one).

The workspace is R7.23's: a `per_part` pipeline declaring `gold/incidents`,
both bars agreed in `judge.yaml`. No run is needed; a judged field's gate reads
the gold set and the pipeline, never what a run produced.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

from dossier.application.eval import CALIBRATIONS_DIR, judge_prompt_hash
from dossier.domain.grounding import DESCRIBED, GROUNDED, judge_name
from dossier.domain.hashing import text_hash

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
JUDGED = "root_cause"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
BOTH_BARS = f"{JUDGED}:\n  {GROUNDED}: 0.95\n  {DESCRIBED}: 0.90\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """`incident-audit` in `per_part` mode, reading page images, with both bars agreed."""
    path = write_pipeline(
        tmp_path, modes={"extract": "per_part"}, inputs={"extract": "documents@page_images"}
    )
    path.write_text(path.read_text(encoding="utf-8") + f"gold: {GOLD}/\n", encoding="utf-8")
    gold = tmp_path / GOLD
    shutil.copytree(FIXTURE_GOLD, gold, dirs_exist_ok=True)
    (gold / "judge.yaml").write_text(BOTH_BARS, encoding="utf-8")
    return tmp_path


def _calibrate(workspace: Path, *, state: str, prompt_hash: str | None = None) -> None:
    """A calibration at 0.97, as `dossier calibrate` would write it (R7.14)."""
    rubric = workspace / "pipelines" / PIPELINE / "rubrics" / f"{JUDGED}.md"
    path = workspace / GOLD / CALIBRATIONS_DIR / f"{judge_name(JUDGED, state)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "judge_model": MODEL,
                "rubric_hash": text_hash(rubric),
                "prompt_hash": prompt_hash or judge_prompt_hash(),
                "agreement": 0.97,
                "sample_size": 22,
            }
        ),
        encoding="utf-8",
    )


def _judged(workspace: Path) -> list[str]:
    from dossier.cli.status import judged_fields

    return judged_fields(workspace, PIPELINE, GOLD)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


class TestStatusNamesWhatEvalWouldWithhold:
    """R17.4 — `eval`'s gate, asked before `eval` is."""

    def test_a_field_calibrated_and_clear_is_reportable(self, workspace: Path):
        """Row 1 — the one measured at 0.97 in both states, under the current judge."""
        _calibrate(workspace, state=GROUNDED)
        _calibrate(workspace, state=DESCRIBED)

        assert _judged(workspace) == [f"{JUDGED} · reportable"]

    def test_a_stale_calibration_is_named_in_evals_words(self, workspace: Path):
        """Row 2 — the one measured under a judge prompt that has since changed."""
        _calibrate(workspace, state=GROUNDED, prompt_hash="sha256:0ld0")
        _calibrate(workspace, state=DESCRIBED)

        assert _judged(workspace) == [
            f"{JUDGED} · withheld: calibration is stale: "
            "the judge prompt has changed since (R7.19)"
        ]

    def test_a_field_never_measured_says_to_calibrate(self, workspace: Path):
        """Row 3 — the one with no calibration file at all."""
        assert _judged(workspace) == [
            f"{JUDGED} · withheld: never measured -- run `dossier calibrate`"
        ]

    def test_the_state_never_measured_is_named(self, workspace: Path):
        """Row 4 — the one whose `described` judge was never measured (R7.23 row 2).

        The pipeline reads page images, so it can answer in either state, and
        both are asked about, as `eval` asks about both.
        """
        _calibrate(workspace, state=GROUNDED)

        assert _judged(workspace) == [
            f"{JUDGED} · withheld: {DESCRIBED}: never measured -- run `dossier calibrate`"
        ]

    def test_without_gold_there_is_no_judged_fields_section(self, workspace: Path, monkeypatch):
        """Row 5, counter-example — the one that names no gold set.

        Nothing under `gold/` is read: the gold set is removed, and `status` is
        none the worse for it.
        """
        shutil.rmtree(workspace / "gold")

        result = _cli(workspace, monkeypatch, "status", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "judged fields" not in result.output

    def test_a_pipeline_that_declares_no_judged_field_says_so(
        self, workspace: Path, monkeypatch
    ):
        """Row 6, counter-example — the one whose `postmortem-review` judges nothing."""
        write_pipeline(workspace, name="postmortem-review", outputs={"extract": None})

        result = _cli(workspace, monkeypatch, "status", "postmortem-review", "--gold", GOLD)

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        heading = lines.index(f"judged fields · postmortem-review against {GOLD}")
        assert lines[heading + 1] == "  no judged fields"
