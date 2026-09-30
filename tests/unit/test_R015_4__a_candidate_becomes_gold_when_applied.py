"""R15.4 — a reviewer's expected value is a gold candidate, and becomes gold only
when a maintainer applies it.

The decisions are the domain's (`dossier.domain.review`): which verdicts are
candidates, what `candidates.jsonl` holds, which candidates are refused, and
the correction a maintainer's signature turns one into. Applying them to a gold
directory is the application's (`apply_candidates`), through `apply_correction`
(R7.7), and all-or-nothing.

`INC-4822`'s gold says `severity: minor` (`tests/fixtures/gold/incidents`); a
reviewer expected `major`. `INC-4830` has no gold file at all.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from dossier.application.review import apply_candidates, pull_reviews
from dossier.domain.review import (
    CANDIDATES,
    Candidate,
    CandidatesRefused,
    Verdict,
    candidates_jsonl,
    candidates_of,
    check_candidates,
    correction_of,
    read_candidates,
)
from dossier.domain.scoring import FieldKind

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"
EXPERIMENT = "dossier-audit/incident-audit/run"
TODAY = date(2026, 9, 25)
KINDS = {
    "loss_amount": FieldKind.AMOUNT,
    "resolution_date": FieldKind.DATE,
    "severity": FieldKind.ENUM,
    "affected_systems": FieldKind.REFERENCE,
    "root_cause": FieldKind.FREE_TEXT,
}
ALLOWED = {"severity": ("minor", "major", "critical")}
STATED = "the renewed TLS certificate was never deployed to the load balancers"


def expected(**overrides) -> Verdict:
    """`s.brunner` expecting `severity` = `major` on `extract · INC-4822`, in the trace view."""
    fields = {
        "run": "20260806T142203Z-4f1a",
        "step": "extract",
        "document": "INC-4822",
        "name": "severity",
        "kind": "expectation",
        "value": "major",
        "rationale": "payments stopped for an hour",
        "reviewer": "User",
        "at": "2026-09-24T09:12:40Z",
        "trace": "tr-4822",
        "assessment": "a-0001",
    }
    return Verdict(**{**fields, **overrides})


def candidate(**overrides) -> Candidate:
    fields = {
        "document": "INC-4822",
        "field": "severity",
        "value": "major",
        "suggested_by": "User",
        "at": "2026-09-24T09:12:40Z",
        "trace": "tr-4822",
        "reason": "payments stopped for an hour",
    }
    return Candidate(**{**fields, **overrides})


class TestWhatACandidateIs:
    """R15.4 — an expectation, never a feedback, and what the file holds of it."""

    def test_an_expected_value_is_a_candidate_and_a_feedback_is_not(self):
        """Row 1: the expectation becomes a candidate; a thumbs-down beside it does not."""
        verdicts = [expected(), expected(kind="feedback", value=False, assessment="a-0002")]

        assert candidates_of(verdicts) == [candidate()]

    def test_the_file_round_trips(self):
        """Row 8's precondition: what a maintainer edits is what is read back."""
        written = candidates_jsonl([candidate(), candidate(document="INC-4830")])

        assert read_candidates(written) == [candidate(), candidate(document="INC-4830")]

    def test_a_line_a_maintainer_broke_is_refused_by_its_number(self):
        """A hand-edited file with a line that is not a candidate says which line."""
        broken = candidates_jsonl([candidate()]) + '{"document": "INC-4830"}\n'

        with pytest.raises(ValueError, match="line 2"):
            read_candidates(broken)


class TestWhatIsRefused:
    """R15.4 rows 5-7 — every problem found, and named, before anything is written."""

    def test_two_reviewers_expecting_different_values_is_a_conflict(self):
        """Row 5: `major` and `critical` for one field of `INC-4822`."""
        other = candidate(value="critical", suggested_by="j.okafor", trace="tr-4822b")

        with pytest.raises(CandidatesRefused) as refused:
            check_candidates([candidate(), other], kinds=KINDS, allowed=ALLOWED)

        said = str(refused.value)
        assert "INC-4822 severity" in said
        assert "'major' (User, tr-4822)" in said and "'critical' (j.okafor, tr-4822b)" in said

    def test_a_name_the_declaration_does_not_have_is_refused(self):
        """Row 6: `summary`, a verdict about the whole answer."""
        with pytest.raises(CandidatesRefused, match="summary is not a field"):
            check_candidates([candidate(field="summary")], kinds=KINDS, allowed=ALLOWED)

    def test_a_value_an_enum_does_not_allow_is_refused(self):
        """Row 7: `catastrophic`, not among `minor`, `major`, `critical`."""
        with pytest.raises(CandidatesRefused, match="minor, major, critical"):
            check_candidates([candidate(value="catastrophic")], kinds=KINDS, allowed=ALLOWED)

    def test_every_problem_is_named_at_once(self):
        """Rows 6 and 7 together: a maintainer fixes the file once, not once per problem."""
        with pytest.raises(CandidatesRefused) as refused:
            check_candidates(
                [candidate(field="summary"), candidate(value="catastrophic")],
                kinds=KINDS,
                allowed=ALLOWED,
            )

        assert len(refused.value.problems) == 2

    def test_two_reviewers_agreeing_are_one_candidate(self):
        """Not a conflict: the same value twice is one answer, the earlier reviewer's."""
        later = candidate(suggested_by="j.okafor", at="2026-09-24T10:00:00Z", trace="tr-b")

        assert check_candidates([later, candidate()], kinds=KINDS, allowed=ALLOWED) == [
            candidate()
        ]


class TestTheMaintainerSigns:
    """R15.4 row 2 — the correction a candidate becomes, under the maintainer's name."""

    def test_the_maintainer_verifies_it_on_the_day_they_apply_it(self):
        """Row 2: `a.aleks`, today, with the trace and the recorded author in the reason."""
        correction = correction_of(candidate(), verified_by="a.aleks", today=TODAY)

        assert (correction.field, correction.value) == ("severity", "major")
        assert (correction.verified_by, correction.verified_at) == ("a.aleks", TODAY)
        assert correction.reason == (
            "expected by User on 2026-09-24 in MLflow trace tr-4822: "
            "payments stopped for an hour"
        )


def _gold(tmp_path: Path) -> Path:
    directory = tmp_path / "gold" / "incidents"
    shutil.copytree(FIXTURE_GOLD, directory)
    return directory


def _write(tmp_path: Path, *candidates: Candidate) -> Path:
    path = tmp_path / "review" / "incident-audit" / CANDIDATES
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(candidates_jsonl(list(candidates)), encoding="utf-8")
    return path


def _apply(tmp_path: Path, path: Path, gold: Path):
    return apply_candidates(
        candidates=path,
        gold=gold,
        kinds=KINDS,
        allowed=ALLOWED,
        verified_by="a.aleks",
        today=TODAY,
    )


class TestApplyingToTheGoldSet:
    """R15.4 rows 1-5 and 8, through `pull_reviews` and `apply_candidates`."""

    def test_a_pull_writes_candidates_and_leaves_gold_alone(self, tmp_path: Path):
        """Row 1: `candidates.jsonl` beside `feedback.jsonl`; `INC-4822.json` untouched."""
        from tests.fakes import FakeReviewSource

        gold = _gold(tmp_path)
        before = (gold / "INC-4822.json").read_bytes()
        directory = tmp_path / "review" / "incident-audit"

        pull_reviews(
            FakeReviewSource({EXPERIMENT: [expected()]}),
            experiment=EXPERIMENT,
            directory=directory,
        )

        assert read_candidates((directory / CANDIDATES).read_text(encoding="utf-8")) == [
            candidate()
        ]
        assert (gold / "INC-4822.json").read_bytes() == before

    def test_applying_signs_the_answer_and_keeps_what_it_replaced(self, tmp_path: Path):
        """Row 2: `severity` is `major`, signed by `a.aleks`, `minor` superseded."""
        gold = _gold(tmp_path)

        applied = _apply(tmp_path, _write(tmp_path, candidate()), gold)

        entry = json.loads((gold / "INC-4822.json").read_text(encoding="utf-8"))["fields"][
            "severity"
        ]
        assert entry["value"] == "major"
        assert (entry["verified_by"], entry["verified_at"]) == ("a.aleks", "2026-09-25")
        assert entry["superseded"] == "minor"
        assert "tr-4822" in entry["reason"] and "User" in entry["reason"]
        assert [(change.document, change.field) for change in applied] == [
            ("INC-4822", "severity")
        ]

    def test_a_document_with_no_gold_file_gets_one(self, tmp_path: Path):
        """Row 3: `INC-4830`'s `root_cause`, which nobody had verified."""
        gold = _gold(tmp_path)
        stated = candidate(document="INC-4830", field="root_cause", value=STATED)

        _apply(tmp_path, _write(tmp_path, stated), gold)

        written = json.loads((gold / "INC-4830.json").read_text(encoding="utf-8"))
        assert written["document"] == "INC-4830"
        assert (written["verified_by"], written["verified_at"]) == ("a.aleks", "2026-09-25")
        assert list(written["fields"]) == ["root_cause"]
        assert written["fields"]["root_cause"]["value"] == STATED

    def test_applying_again_changes_nothing(self, tmp_path: Path):
        """Row 4: the value is already gold, so the file is the same bytes."""
        gold = _gold(tmp_path)
        path = _write(tmp_path, candidate())
        _apply(tmp_path, path, gold)
        before = (gold / "INC-4822.json").read_bytes()

        applied = _apply(tmp_path, path, gold)

        assert applied == []
        assert (gold / "INC-4822.json").read_bytes() == before

    def test_a_conflict_writes_no_file_at_all(self, tmp_path: Path):
        """Row 5: refused before a file is written, `INC-4830`'s good candidate included."""
        gold = _gold(tmp_path)
        before = sorted(path.name for path in gold.iterdir())
        path = _write(
            tmp_path,
            candidate(document="INC-4830", field="root_cause", value=STATED),
            candidate(),
            candidate(value="critical", suggested_by="j.okafor", trace="tr-4822b"),
        )

        with pytest.raises(CandidatesRefused):
            _apply(tmp_path, path, gold)

        assert sorted(path.name for path in gold.iterdir()) == before

    def test_a_line_the_maintainer_deleted_is_not_applied(self, tmp_path: Path):
        """Row 8: the file as the maintainer left it is the decision."""
        gold = _gold(tmp_path)
        path = _write(
            tmp_path,
            candidate(),
            candidate(document="INC-4830", field="root_cause", value=STATED),
        )
        kept = path.read_text(encoding="utf-8").splitlines()[1:]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")

        _apply(tmp_path, path, gold)

        assert (gold / "INC-4830.json").exists()
        severity = json.loads((gold / "INC-4822.json").read_text(encoding="utf-8"))["fields"][
            "severity"
        ]
        assert severity["value"] == "minor"

    def test_a_line_left_blank_is_not_the_end_of_the_file(self, tmp_path: Path):
        """Row 10: the maintainer blanked the first candidate's line, not deleted it."""
        gold = _gold(tmp_path)
        path = _write(
            tmp_path,
            candidate(),
            candidate(document="INC-4830", field="root_cause", value=STATED),
        )
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(["", *lines[1:]]) + "\n", encoding="utf-8")

        _apply(tmp_path, path, gold)

        assert (gold / "INC-4830.json").exists()
