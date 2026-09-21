"""Fixtures shared by more than one acceptance test.

`two_runs` builds the comparison example of `_fixtures.md` — the same four
documents run twice, the second time answering differently — which R11.8 and
R11.10 both need and neither owns. A fixture imported from another test module
makes pytest re-collect that module's tests under this one's name, so it lives
here instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ANSWERS_AFTER,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

GOLD = "gold/incidents"
URI = "http://localhost:5000"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _calibrate(workspace: Path) -> None:
    """A judge measured and comfortably clear of its bar (R7.15).

    `root_cause` is judged, and a withheld field prints a reason and no delta —
    which would leave every assertion here about the withheld line instead.
    """
    gold = workspace / "gold" / "incidents"
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "calibrations").mkdir(exist_ok=True)
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": RoutedModel.model_id,
                "rubric_hash": text_hash(
                    workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
                ),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def two_runs(workspace: Path, monkeypatch) -> tuple[Path, str, str]:
    """The same four documents run twice, the second time answering differently.

    Tracking is off for both runs, so the only MLflow run a test then sees is the
    one it is about (R11.1 records a run of its own).
    """
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output

    ids: list[str] = []
    for answers in (ANSWERS, ANSWERS_AFTER):
        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id, a=answers: RoutedModel(a)
        )
        # The prompt moves between the two runs, so the second is a different
        # configuration rather than the same one served from cache (R5.2).
        prompt = workspace / "pipelines" / PIPELINE / "prompts" / "extract.md"
        prompt.write_text(
            prompt.read_text(encoding="utf-8") + f"\n{len(ids)}\n", encoding="utf-8"
        )
        ran = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert ran.exit_code == 0, ran.output
        # Read off the line the command prints rather than by listing `runs/`:
        # both runs land in the same second and their suffixes are random, so
        # sorting the directory names returns whichever sorts last, twice.
        found = re.search(r"^run (\S+)", ran.output, re.MULTILINE)
        assert found, ran.output
        ids.append(found.group(1))
    assert ids[0] != ids[1], "two runs, two ids"

    _calibrate(workspace)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace, ids[0], ids[1]
