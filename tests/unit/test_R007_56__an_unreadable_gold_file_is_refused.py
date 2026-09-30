"""R7.56 — a gold file that cannot be read as verified answers is refused before
anything is scored, naming the file and what stops it.

R7.44 refuses an answer that reads, in a shape no run can meet. A file that does
not read at all stopped `dossier eval` on a traceback, the JSON parser's or
pydantic's, which names neither the file nor the field. The decision is
`read_gold_file`: a file's name and text in, its verified answers or every line
that stops them out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.acceptance.test_R017_7__status_says_what_eval_will_withhold import (
    GOLD,
    _cli,
    audited_workspace,
)
from tests.scoring_example import PIPELINE

from dossier.domain.gold import UnreadableGold, read_gold_file

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"


def fixture(document: str) -> dict:
    return json.loads((FIXTURE_GOLD / f"{document}.json").read_text(encoding="utf-8"))


def refusal(name: str, text: str) -> tuple[str, ...]:
    with pytest.raises(UnreadableGold) as refused:
        read_gold_file(name, text)
    return refused.value.lines


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """R17.7's workspace: synced and run, a bar and a sample beside the gold set."""
    return audited_workspace(workspace, monkeypatch)


class TestAnUnreadableGoldFileIsRefused:
    """R7.56 — refused before scoring, naming the file and what stops it."""

    def test_a_value_of_no_gold_shape_is_named_with_the_shapes_gold_holds(self):
        """Row 1 — the one writing an amount as an array of one number."""
        gold = fixture("INC-4821")
        gold["fields"]["loss_amount"] = {"value": [48200.0], "currency": "CHF"}

        assert refusal("INC-4821.json", json.dumps(gold)) == (
            "INC-4821.json: loss_amount holds [48200.0], and a gold value is a number, "
            "a string, true or false, a list of strings, or null",
        )

    def test_a_file_that_is_not_json_is_named_with_where_the_parser_stopped(self):
        """Row 2 — the one cut off before its closing brace.

        The position and not the parser's message: its words change between
        Python versions, and the line and column are what a person looks for.
        """
        text = '{\n  "document": "INC-4822",\n  "verified_by": "a.aleks"\n'

        assert refusal("INC-4822.json", text) == ("INC-4822.json: not JSON (line 4, column 1)",)

    def test_an_answer_nobody_verified_is_refused(self):
        """Row 3 — the one with no `verified_by` (R7.7)."""
        gold = fixture("INC-4901")
        del gold["verified_by"]

        assert refusal("INC-4901.json", json.dumps(gold)) == (
            "INC-4901.json: verified_by is missing",
        )

    def test_a_verification_date_that_is_not_a_date_is_named(self):
        """Row 4 — the one verified on "15 September 2026"."""
        gold = fixture("INC-5455")
        gold["verified_at"] = "15 September 2026"

        assert refusal("INC-5455.json", json.dumps(gold)) == (
            "INC-5455.json: verified_at '15 September 2026' is not a date, "
            "written as 2026-09-15",
        )

    def test_eval_names_every_unreadable_file_and_scores_nothing(
        self, audited: Path, monkeypatch
    ):
        """Row 5 — the one with rows 1 and 3 in one gold set.

        Every file is named, in file order, so one pass finds them all, as
        every refused answer is (R7.44).
        """
        amount = fixture("INC-4821")
        amount["fields"]["loss_amount"] = {"value": [48200.0], "currency": "CHF"}
        (audited / GOLD / "INC-4821.json").write_text(json.dumps(amount), encoding="utf-8")
        unverified = fixture("INC-4901")
        del unverified["verified_by"]
        (audited / GOLD / "INC-4901.json").write_text(json.dumps(unverified), encoding="utf-8")

        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr.splitlines() == [
            f"{PIPELINE}: INC-4821.json: loss_amount holds [48200.0], and a gold value is "
            "a number, a string, true or false, a list of strings, or null",
            f"{PIPELINE}: INC-4901.json: verified_by is missing",
        ]

    def test_a_file_as_the_fixtures_hold_it_is_read(self):
        """Row 6, counter-example — the one `tests/fixtures/gold/incidents/` holds."""
        text = (FIXTURE_GOLD / "INC-4821.json").read_text(encoding="utf-8")

        gold = read_gold_file("INC-4821.json", text)

        assert gold.document == "INC-4821"
        assert gold.fields["loss_amount"] == {"value": 48200.00, "currency": "CHF"}

    def test_anything_else_refused_is_named_in_pydantics_words_after_the_key(self):
        """Row 7 — the one whose currency is the number 5."""
        gold = fixture("INC-4821")
        gold["fields"]["loss_amount"]["currency"] = 5

        assert refusal("INC-4821.json", json.dumps(gold)) == (
            "INC-4821.json: loss_amount.currency: Input should be a valid string",
        )

    def test_a_field_refused_on_two_keys_is_named_on_both(self):
        """Row 8 — the one whose value is an array and whose currency is a number.

        Pydantic refuses the value once for each shape it tried. The repeats
        are dropped, and the currency after them must not be dropped with them.
        """
        gold = fixture("INC-4821")
        gold["fields"]["loss_amount"] = {"value": [48200.0], "currency": 5}

        assert refusal("INC-4821.json", json.dumps(gold)) == (
            "INC-4821.json: loss_amount holds [48200.0], and a gold value is a number, "
            "a string, true or false, a list of strings, or null",
            "INC-4821.json: loss_amount.currency: Input should be a valid string",
        )
