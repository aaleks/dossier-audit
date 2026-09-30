"""R17.7 — what `dossier status` says `dossier eval` will withhold is what it withholds.

The outer loop of spec 017. `status` exists to say, before a run is paid for,
which judged fields `eval` will refuse to report. That is only worth anything if
the two agree: a `status` that called a field reportable while `eval` withheld
it would be worse than no `status` at all. So the test runs both, on one
workspace, and holds `eval` to the words `status` printed.

Built from R7.15's workspace (synced and run, the bar declared beside the gold
set) and R7.14's twenty-case sample, so no calibration exists until the third
row makes one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.acceptance.test_R007_14__calibrate_writes_the_calibration_file import (
    _cases,
    _replies,
)
from tests.fakes import FakeModelClient, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    FIELDS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

JUDGED = "root_cause"
GOLD = "gold/incidents"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """Synced and run, with a bar and a sample beside the gold set, and no calibration."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output

    gold = workspace / "gold" / "incidents"
    (gold / "samples").mkdir(parents=True, exist_ok=True)
    (gold / "judge.yaml").write_text(f"{JUDGED}: 0.95\n", encoding="utf-8")
    (gold / "samples" / f"{JUDGED}.jsonl").write_text(
        "\n".join(json.dumps(case) for case in _cases()) + "\n", encoding="utf-8"
    )
    # Neither `status` nor `eval` asks a model (R7.10); a call would be a finding.
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


def _status(workspace: Path, monkeypatch):
    return _cli(workspace, monkeypatch, "status", PIPELINE, "--gold", GOLD)


def _eval(workspace: Path, monkeypatch):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


def _judged_line(output: str) -> str:
    """`status`'s line for the judged field, under its `judged fields` heading."""
    lines = output.splitlines()
    heading = next(at for at, line in enumerate(lines) if line.startswith("judged fields"))
    return next(line.strip() for line in lines[heading + 1 :] if line.split()[0] == JUDGED)


def _eval_line(output: str) -> str:
    """`eval`'s line for the judged field, in its per-field report."""
    return next(
        line
        for line in output.splitlines()
        if (words := line.split()) and words[0] == JUDGED and words[0] in FIELDS
    )


class TestStatusSaysWhatEvalWillWithhold:
    """R17.7 — `status`'s prediction and `eval`'s verdict are one decision, said twice."""

    def test_status_names_the_field_eval_will_withhold(self, audited: Path, monkeypatch):
        """Row 1 — the one run and never calibrated."""
        result = _status(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        headings = [line for line in result.output.splitlines() if not line.startswith(" ")]
        assert headings[:2] == ["sources", "pipelines"], result.output
        assert headings[2].startswith("judged fields"), result.output
        assert _judged_line(result.output).startswith(f"{JUDGED} · withheld: never measured"), (
            result.output
        )

    def test_eval_withholds_it_in_the_words_status_printed(self, audited: Path, monkeypatch):
        """Row 2 — the one where `eval` then gives the same reason, word for word."""
        said = _judged_line(_status(audited, monkeypatch).output)
        reason = said.split("withheld: ", 1)[1]

        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        line = _eval_line(result.output)
        assert re.search(r"\d+\.\d%", line) is None, line
        assert reason in line, f"status said {reason!r}; eval printed {line!r}"

    def test_after_calibrate_both_call_it_reportable(self, audited: Path, monkeypatch):
        """Row 3, counter-example — the one calibrated at 20 of 20 against a bar of 0.95."""
        import dossier.cli.bootstrap as cli

        judge = FakeModelClient(responses=_replies(_cases()))
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
        calibrated = _cli(audited, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)
        assert calibrated.exit_code == 0, calibrated.output
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        status = _status(audited, monkeypatch)
        result = _eval(audited, monkeypatch)

        assert status.exit_code == 0, status.output
        assert _judged_line(status.output) == f"{JUDGED} · reportable", status.output
        assert result.exit_code == 0, result.output
        assert re.search(r"\d+\.\d%", _eval_line(result.output)), result.output
