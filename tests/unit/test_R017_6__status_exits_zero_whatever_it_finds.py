"""R17.6 — `dossier status` exits 0 whatever it finds, and 2 only when it cannot answer.

It informs; `eval` and `calibrate` are the gates. A status that failed on a
stale calibration or an owed page would stop a script for something the script
was asking about. It fails only when the question cannot be answered: a gold
set named without the pipeline it would be judged for (R3.7), a pipeline that
does not exist, or one `eval` would refuse to score.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.acceptance.test_R017_7__status_says_what_eval_will_withhold import (
    GOLD,
    _cli,
    audited_workspace,
)
from tests.pipelines import write_pipeline
from tests.scoring_example import PIPELINE, SOURCE_ID, SOURCE_TYPE

from dossier.infrastructure.ledger import Ledger


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """R17.7's workspace: synced and run, a bar and a sample beside the gold set."""
    return audited_workspace(workspace, monkeypatch)


def _sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    heading = ""
    for line in output.splitlines():
        if line.startswith("  "):
            sections[heading].append(line.strip())
        else:
            heading = line.split(" · ")[0]
            sections[heading] = []
    return sections


class TestStatusExitsZeroWhateverItFinds:
    """R17.6 — 0 for everything it finds, 2 for a question it cannot answer."""

    def test_owed_never_synced_and_withheld_is_still_exit_zero(
        self, audited: Path, monkeypatch
    ):
        """Row 1 — the one where everything that could need attention does."""
        (audited / "sources.yaml").write_text(
            f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
            f"  - id: procedures-confluence\n    type: {SOURCE_TYPE}\n",
            encoding="utf-8",
        )
        with Ledger(audited) as ledger:
            ledger.owe(
                SOURCE_ID,
                "INC-4821/report.pdf",
                item_key="INC-4821",
                at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
                error="timed out",
            )

        result = _cli(audited, monkeypatch, "status", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert "procedures-confluence · never synced" in result.output
        assert "owed INC-4821/report.pdf" in result.output
        assert "root_cause · withheld" in result.output

    def test_a_pipeline_argument_narrows_the_pipelines_and_not_the_sources(
        self, audited: Path, monkeypatch
    ):
        """Row 2 — the one asked about `incident-audit` beside `postmortem-review`."""
        write_pipeline(audited, name="postmortem-review")

        narrowed = _sections(_cli(audited, monkeypatch, "status", PIPELINE).output)
        whole = _sections(_cli(audited, monkeypatch, "status").output)

        assert [line.split(" · ")[0] for line in narrowed["pipelines"]] == [PIPELINE]
        assert [line.split(" · ")[0] for line in whole["pipelines"]] == [
            PIPELINE,
            "postmortem-review",
        ]
        assert narrowed["sources"] == whole["sources"]

    def test_gold_without_a_pipeline_is_refused(self, audited: Path, monkeypatch):
        """Row 3, counter-example — the one naming a gold set and no pipeline.

        A gold set can serve several pipelines (R3.7), and its judges are
        checked against a pipeline's rubrics, so there is no one answer to give.
        """
        result = _cli(audited, monkeypatch, "status", "--gold", GOLD)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert "PIPELINE" in result.stderr and "R3.7" in result.stderr

    def test_a_pipeline_that_does_not_exist_is_named_as_eval_names_it(
        self, audited: Path, monkeypatch
    ):
        """Row 4, counter-example — the one that misspells `incident-audit`."""
        status = _cli(audited, monkeypatch, "status", "incident-audti")
        eval_ = _cli(audited, monkeypatch, "eval", "incident-audti", "--gold", GOLD)

        assert status.exit_code == 2
        assert "incident-audti" in status.stderr
        assert status.stderr == eval_.stderr

    def test_a_pipeline_declaring_two_outputs_is_refused_as_eval_refuses_it(
        self, audited: Path, monkeypatch
    ):
        """Row 5, counter-example — the one where `extract` and `verify` both declare one.

        `eval` scores exactly one output, and refuses to guess which (spec 007).
        Answering from the first would be that guess, said before `eval` is run.
        """
        write_pipeline(audited, steps=["extract", "verify"], sources=[SOURCE_ID])

        status = _cli(audited, monkeypatch, "status", PIPELINE, "--gold", GOLD)
        eval_ = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert status.exit_code == 2
        assert status.stdout == ""
        assert status.stderr == (
            f"{PIPELINE}: 2 steps declare an output; eval scores exactly one\n"
        )
        assert status.stderr == eval_.stderr

    def test_a_pipeline_declaring_no_output_is_refused_as_eval_refuses_it(
        self, audited: Path, monkeypatch
    ):
        """Row 6, counter-example — the one whose `postmortem-review` declares no output."""
        write_pipeline(audited, name="postmortem-review", outputs={"extract": None})

        status = _cli(audited, monkeypatch, "status", "postmortem-review", "--gold", GOLD)
        eval_ = _cli(audited, monkeypatch, "eval", "postmortem-review", "--gold", GOLD)

        assert status.exit_code == 2
        assert status.stdout == ""
        assert status.stderr == (
            "postmortem-review: 0 steps declare an output; eval scores exactly one\n"
        )
        assert status.stderr == eval_.stderr
