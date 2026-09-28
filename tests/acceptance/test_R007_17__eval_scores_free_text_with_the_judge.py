"""R7.17 — a free-text field with a value in gold and a grounded value in the run
is scored by the judge, asked the calibrated question of the run's answer.

Until this rule, `dossier eval` deferred every free-text verdict to a judge and
then dropped it: `root_cause 50.0%` was a percentage over the abstention cases
alone, and the whole gate -- threshold, sample, calibration, withholding --
guarded a number nothing produced. The test is an acceptance test because that
is where the defect was: every unit beneath it was green.

`INC-4830` is the document that states its root cause (`_fixtures.md`), held
here beside the scoring example's four. Its gold file is written into the
workspace copy, as the bar and the sample are, and holds only `root_cause`: a
field absent from gold is not scored (R7.3 row 4), so the other four say nothing
about the four abstention verdicts this test counts alongside the judged one.

The judge is a `FakeModelClient` scripted to one verdict, and it **counts
calls**: four of the seven rows are claims that the judge was not asked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ANSWERS_AFTER,
    FIELDS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
    abstains,
    found,
)

from dossier.domain.hashing import text_hash

JUDGED = "root_cause"
GOLD = "gold/incidents"
BAR = 0.95
JUDGE_MODEL = RoutedModel.model_id

# `_fixtures.md`, "Fields on INC-4830": the stated cause, and the two committed
# candidates -- rc-01 supported, rc-02 the planted claim (R7.12).
STATED = "the renewed TLS certificate was never deployed to the load balancers"
RC_01 = (
    "The renewed TLS certificate was issued into Vault but never deployed to the "
    "load balancers, because deployment needed a Terraform apply that nobody ran; "
    "the expiry alert went to an archived Slack channel."
)
RC_02 = "The quarter-end change freeze caused the checkout outage."

INC_4830 = (
    "# INC-4830\n\n"
    "Checkout was unavailable for 41 minutes on 2026-08-14.\n"
    f"{RC_01}\n"
    "A quarter-end change freeze was in effect and is noted as a contributing factor.\n"
)


def _answers(candidate: str, *, span: str) -> dict:
    """The scoring example's answers, plus `INC-4830` answering `candidate` for its cause."""
    return {
        **ANSWERS,
        "INC-4830": [
            *(abstains(field) for field in FIELDS if field != JUDGED),
            found("INC-4830", JUDGED, candidate, span),
        ],
    }


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _field_lines(output: str) -> dict[str, str]:
    return {
        words[0]: line
        for line in output.splitlines()
        if (words := line.split()) and words[0] in FIELDS
    }


def _percentage(line: str) -> str | None:
    match = re.search(r"\d+\.\d%", line)
    return match.group() if match else None


def _rubric(workspace: Path) -> Path:
    return workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"


def _calibrated(workspace: Path, *, agreement: float = 1.0) -> None:
    """What `dossier calibrate` leaves behind for an eligible judge (R7.14, R7.19).

    The prompt hash is imported inside the helper: until R7.19 lands, collecting
    the default suite would error on a name that does not exist yet.
    """
    from dossier.application.eval import judge_prompt_hash

    directory = workspace / "gold" / "incidents" / "calibrations"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{JUDGED}.json").write_text(
        json.dumps(
            {
                "judge_model": JUDGE_MODEL,
                "rubric_hash": text_hash(_rubric(workspace)),
                "prompt_hash": judge_prompt_hash(),
                "agreement": agreement,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _verdict(supported: bool, evidence: str) -> str:
    return json.dumps({"supported": supported, "evidence": evidence})


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The scoring example's four documents and `INC-4830`, synced, with the bar declared."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({**ISSUES, "INC-4830": INC_4830}),
    )
    gold = workspace / "gold" / "incidents"
    (gold / "judge.yaml").write_text(f"{JUDGED}: {BAR}\n", encoding="utf-8")
    (gold / "INC-4830.json").write_text(
        json.dumps(
            {
                "document": "INC-4830",
                "verified_by": "a.aleks",
                "verified_at": "2026-09-17",
                "fields": {JUDGED: {"value": STATED}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


def _run(workspace: Path, monkeypatch, answers) -> str:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(answers))
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)


def _judge(monkeypatch, *replies: str) -> FakeModelClient:
    """The judge `dossier eval` asks, scripted; it counts what it was asked."""
    import dossier.cli.bootstrap as cli

    judge = FakeModelClient(responses=list(replies))
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
    return judge


def _eval(workspace: Path, monkeypatch, *extra: str):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, *extra)


class TestEvalScoresFreeTextWithTheJudge:
    """R7.17 — the judge is asked the calibrated question, and only what is left."""

    def test_a_supported_answer_is_correct(self, held: Path, monkeypatch):
        """Example 1: the one where the run's cause is the document's.

        One call, and the field's percentage counts it: three of five, not the
        two of four the abstention verdicts alone would give.
        """
        _run(held, monkeypatch, _answers(RC_01, span=RC_01))
        _calibrated(held)
        judge = _judge(monkeypatch, _verdict(True, "the certificate paragraph says so"))

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        assert judge.call_count == 1, "one judged field, one judge call"
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) == "60.0%", line

    def test_the_planted_claim_is_incorrect_with_the_judges_evidence(
        self, held: Path, monkeypatch
    ):
        """Example 2: the one where the run offers the quarter-end freeze as the cause.

        Grounded -- the freeze is in the document as a contributing factor -- so
        R7.4 does not decide it; the judge does, and says why (R7.12). The
        evidence is the verdict's detail, proved at the decision (the unit test
        beside this one): the report prints per-field lines, and the file that
        would show a person the detail is the review loop's, which spec 007
        describes and nothing writes yet.
        """
        _run(
            held, monkeypatch, _answers(RC_02, span="A quarter-end change freeze was in effect")
        )
        _calibrated(held)
        evidence = "the document names the freeze only as a contributing factor"
        judge = _judge(monkeypatch, _verdict(False, evidence))

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        assert judge.call_count == 1
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) == "40.0%", line
        assert "(1 judged)" in line

    def test_the_report_says_how_many_verdicts_were_judged(self, held: Path, monkeypatch):
        """Example 3: the one where the line says `(1 judged)`.

        The count is printed, never implied. A percentage over an unknown mix
        of abstention verdicts and judged ones is the silent subset this rule
        replaces.
        """
        _run(held, monkeypatch, _answers(RC_01, span=RC_01))
        _calibrated(held)
        _judge(monkeypatch, _verdict(True, "stated"))

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        line = _field_lines(result.output)[JUDGED]
        assert "60.0%" in line and "(1 judged)" in line, line

    def test_abstention_is_decided_without_the_judge(self, held: Path, monkeypatch):
        """Counter-example (row 4): the one R7.3 decides -- gold null, or the run abstains.

        The scoring example alone: every gold `root_cause` is null, so every
        verdict is R7.3's and the judge is asked nothing. A judge that fails on
        any call is the assertion.
        """
        import dossier.cli.bootstrap as cli

        (held / "gold" / "incidents" / "INC-4830.json").unlink()
        _run(held, monkeypatch, _answers(RC_01, span=RC_01))
        _calibrated(held)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _percentage(_field_lines(result.output)[JUDGED]) == "50.0%"

    def test_an_ungrounded_value_is_decided_without_the_judge(self, held: Path, monkeypatch):
        """Counter-example (row 5): the one whose span is nowhere in the document.

        R7.4 scores it incorrect before the field's type is consulted, so the
        judge is never asked about a claim the document could not have supported.
        """
        import dossier.cli.bootstrap as cli

        _run(held, monkeypatch, _answers(RC_01, span="a sentence the document does not hold"))
        _calibrated(held)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        assert _percentage(_field_lines(result.output)[JUDGED]) == "40.0%"

    def test_a_withheld_field_is_not_judged(self, held: Path, monkeypatch):
        """Counter-example (row 6): the one nobody may quote.

        No calibration, so R7.15 withholds the field -- and the judge is not
        asked either. Nothing is measured for a number nobody may quote.
        """
        import dossier.cli.bootstrap as cli

        _run(held, monkeypatch, _answers(RC_01, span=RC_01))
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _eval(held, monkeypatch)

        assert result.exit_code == 0, result.output
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) is None, line
        assert "never measured" in line

    def test_a_comparison_is_gated_on_both_sides(self, held: Path, monkeypatch):
        """Counter-example (row 7): the one where `--compare` would quote a withheld number.

        The change gate is the place a judge's figure is most likely to be
        quoted, and it is gated the same way: withheld on both sides, with its
        reason, and no delta.
        """
        import dossier.cli.bootstrap as cli

        a = _run(held, monkeypatch, _answers(RC_01, span=RC_01))
        prompt = held / "pipelines" / PIPELINE / "prompts" / "extract.md"
        prompt.write_text(
            "Read carefully.\n" + prompt.read_text(encoding="utf-8"), encoding="utf-8"
        )
        b = _run(
            held,
            monkeypatch,
            {**ANSWERS_AFTER, "INC-4830": _answers(RC_01, span=RC_01)["INC-4830"]},
        )
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _eval(held, monkeypatch, "--compare", a, b)

        assert result.exit_code == 0, result.output
        line = _field_lines(result.output)[JUDGED]
        assert _percentage(line) is None, line
        assert not re.search(r"(?<!\S)[+-]\d+\.\d(?!\S)", line), "no delta for a withheld field"
        assert "never measured" in line
