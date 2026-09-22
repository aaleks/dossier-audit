"""R11.17 - every command's record describes itself from the lines it printed.

R11.12 proved `eval` and `eval --compare` describe themselves. The four commands
that do the work opened a record whose Description -- the first thing on its
page -- was empty, so eight `sync incident-audit` records in a list were eight
identical rows.

Every assertion here takes a line out of the command's own output and looks for
that same line in the record. Verbatim, indentation stripped: a figure that moves
in the terminal and not in the record fails here rather than drifting quietly.

The tracking-off counter-example (row 7) is R10.4's and is proved there -- nothing
tracking does reaches disk. This file is about what reaches the server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, FakeTracker, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

URI = "http://localhost:5000"
GOLD = "gold/incidents"
NOTE = "mlflow.note.content"
FIELD = "root_cause"

# Twenty cases over the four documents the source holds, as R7.11's sample is.
VERDICTS = [True] * 12 + [False] * 8


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _answer_with(monkeypatch, model) -> None:
    """The seam every other acceptance test uses: the CLI's model builder."""
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)


def _cases() -> list[dict]:
    keys = sorted(ISSUES)
    return [
        {
            "document": keys[index % len(keys)],
            "answer": f"candidate answer {index}",
            "supported": supported,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-15",
        }
        for index, supported in enumerate(VERDICTS)
    ]


def _line(output: str, starting: str) -> str:
    """The one printed line beginning with `starting`, indentation stripped."""
    for line in output.splitlines():
        if line.strip().startswith(starting):
            return line.strip()
    raise AssertionError(f"no line starting {starting!r} in:\n{output}")


class GarbledOnOne(RoutedModel):
    """The scoring example's answers, except for one document it garbles.

    A reply nothing can parse fails that document after its retry (R6.9) and
    leaves the other three alone, which is the run row 2 is about: partly done,
    exit code 1, and still a record worth opening.
    """

    bad = "INC-4822"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        reply = super().complete(prompt, schema=schema, parts=parts)
        return "not json at all" if self.calls[-1] == self.bad else reply


@pytest.fixture
def declared(workspace: Path, monkeypatch) -> Path:
    """The scoring example's four incidents, behind a pipeline and a gold set."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, sources=[SOURCE_ID])
    path.write_text(path.read_text(encoding="utf-8") + f"gold: {GOLD}/\n", encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    gold = workspace / "gold" / "incidents"
    (gold / "samples").mkdir(parents=True)
    (gold / "judge.yaml").write_text(f"{FIELD}: 0.95\n", encoding="utf-8")
    (gold / "samples" / f"{FIELD}.jsonl").write_text(
        "\n".join(json.dumps(case) for case in _cases()) + "\n", encoding="utf-8"
    )
    return workspace


@pytest.fixture
def tracker(declared: Path, monkeypatch) -> FakeTracker:
    """Tracking switched on the way a person switches it on, at a fake (R10.1)."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


def _described(tracker: FakeTracker) -> str:
    assert len(tracker.runs) == 1, f"one command is one MLflow run; got {len(tracker.runs)}"
    note = tracker.runs[0].tags.get(NOTE)
    assert note, "the record carries no description"
    return note


class TestEveryRecordDescribesItself:
    """R11.17 - the record says what the command did, in the command's own words."""

    def test_a_sync_describes_what_it_fetched(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 3: the one where the per-source line is on the record.

        Both lines the command prints about its work -- the source's counts and
        what the ledger did with them -- because `4 fetched` and `4 new
        snapshots` are different claims, and a sync that fetched everything and
        wrote nothing is the normal second sync over a folder source (R2.5).
        """
        result = _cli(declared, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        described = _described(tracker)
        assert _line(result.output, SOURCE_ID) in described
        assert _line(result.output, "ledger updated") in described

    def test_a_convert_describes_what_it_converted(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 4: the one where held, converted and cached are on the record."""
        assert _cli(declared, monkeypatch, "sync", PIPELINE).exit_code == 0
        tracker.runs.clear()

        result = _cli(declared, monkeypatch, "convert", PIPELINE)

        assert result.exit_code == 0, result.output
        described = _described(tracker)
        assert _line(result.output, SOURCE_ID) in described
        assert _line(result.output, "cache updated") in described

    def test_a_run_describes_each_step_it_ran(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where every step's line is on the record.

        The run id, the pinned model and the pipeline hash first -- the three
        params R11.1 already records, said in a sentence -- then one line per
        step, exactly as the terminal printed it. A record naming only the run
        would say no more than its own title already does (R10.10).
        """
        assert _cli(declared, monkeypatch, "sync", PIPELINE).exit_code == 0
        tracker.runs.clear()
        _answer_with(monkeypatch, RoutedModel(ANSWERS))

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        described = _described(tracker)
        assert re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1) in described
        assert RoutedModel.model_id in described
        steps = [
            line.strip()
            for line in result.output.splitlines()
            if re.match(r"^  \w[\w-]*: \d+ document", line)
        ]
        assert steps, result.output
        for line in steps:
            assert line in described

    def test_a_run_with_a_failed_document_is_described_all_the_same(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where the run went wrong and said so.

        `INC-4822` fails after its retry; the other three documents complete.
        The record closes FAILED and carries the same lines the terminal showed,
        failure count included. A description written only on success would make
        a failed run look like a command nobody ran (R8.6).
        """
        assert _cli(declared, monkeypatch, "sync", PIPELINE).exit_code == 0
        tracker.runs.clear()
        _answer_with(monkeypatch, GarbledOnOne(ANSWERS))

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 1, result.output
        described = _described(tracker)
        assert "1 failed" in described
        assert _line(result.output, "extract:") in described

    def test_a_calibration_describes_what_it_measured(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 5: the one where the agreement figure is on the record.

        The line the terminal prints (R7.14), which already carries the field,
        the agreement, the case count and the judge. The bar is not on that line
        and is not added here: a calibration never reads `judge.yaml`, and a
        record holding both would read as having applied it (R7.14 row 5).
        """
        assert _cli(declared, monkeypatch, "sync", PIPELINE).exit_code == 0
        tracker.runs.clear()
        _answer_with(
            monkeypatch,
            FakeModelClient(
                responses=[json.dumps({"supported": case["supported"]}) for case in _cases()]
            ),
        )

        result = _cli(declared, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        described = _described(tracker)
        assert _line(result.output, FIELD) in described
        assert f"gold {Path(GOLD).name}" in described

    def test_a_run_that_counted_nothing_describes_nothing(
        self, declared: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example, row 6: the one where the run stops at its first miss.

        A model this machine cannot reach stops the run before any step completes
        (R9.2 row 3), so there is no count to restate. The record still closes --
        a command that ran is a command that happened -- and it closes with no
        description rather than with an invented one.
        """
        assert _cli(declared, monkeypatch, "sync", PIPELINE).exit_code == 0
        tracker.runs.clear()
        _answer_with(monkeypatch, NoModelClient())

        result = _cli(declared, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        assert len(tracker.runs) == 1
        assert NOTE not in tracker.runs[0].tags
