"""What reviewers said about a pipeline's answers, read back from MLflow (spec 015).

A verdict is one assessment a person left on one of a pipeline's traces: a
thumbs-up or -down on a field or on the whole answer (feedback), or the value
that should have been there (an expectation). This module decides what is
written of them and what is said -- the file a maintainer diffs and the report
prompt work starts from -- from verdicts it is handed. Reading them is the
`ReviewSource` port's business, and only `dossier review pull` builds one
(R15.5).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from itertools import groupby
from typing import Literal

from dossier.domain.gold import Correction
from dossier.domain.scoring import FieldKind

__all__ = [
    "CANDIDATES",
    "FEEDBACK",
    "Candidate",
    "CandidatesRefused",
    "Verdict",
    "candidates_jsonl",
    "candidates_of",
    "check_candidates",
    "correction_of",
    "feedback_jsonl",
    "read_candidates",
    "review_report",
]

# Where `dossier review pull` writes every verdict, and every expected value as a
# gold candidate, under `review/<pipeline>/` (R15.3, R15.4).
FEEDBACK = "feedback.jsonl"
CANDIDATES = "candidates.jsonl"


@dataclass(frozen=True)
class Verdict:
    """One valid verdict a person left on one of a pipeline's traces (R15.3).

    `reviewer` is the author as MLflow recorded it: `User` for everyone who used
    the open-source trace view, which sends that string whoever is logged in,
    and a real name for a verdict logged through the API. It is reported as it
    is, and never guessed at.
    """

    run: str
    step: str
    document: str
    name: str
    kind: Literal["feedback", "expectation"]
    value: object
    rationale: str | None
    reviewer: str
    at: str
    trace: str
    assessment: str

    # A value can be a list or a mapping, which no hash can take; nothing needs
    # a verdict in a set, and equality is what the tests and the file lean on.
    __hash__ = None  # type: ignore[assignment]


def _order(verdict: Verdict) -> tuple[str, ...]:
    return (
        verdict.run,
        verdict.step,
        verdict.document,
        verdict.name,
        verdict.at,
        verdict.assessment,
    )


def feedback_jsonl(verdicts: Sequence[Verdict]) -> str:
    """Every verdict, one JSON object per line, in one order (R15.3).

    Sorted by where and when it was left, keys sorted within each line, so the
    same verdicts are the same bytes however the server listed them -- and a
    second pull with nothing new leaves `git diff` empty (R15.3 row 4, R0.4).
    """
    return "".join(
        json.dumps(asdict(verdict), sort_keys=True, ensure_ascii=False) + "\n"
        for verdict in sorted(verdicts, key=_order)
    )


def review_report(verdicts: Sequence[Verdict]) -> list[str]:
    """What reviewers said, by step and name: where prompt work starts (R15.3).

    Each step and verdict name gets one line: how many said yes, how many said
    no, and how many gave the value they expected. Beneath it, each no -- and
    each feedback that was neither yes nor no -- with its document, its author
    and its reason, because a count of disagreements says where to look and
    only the reasons say what to change.
    """
    lines: list[str] = []
    ordered = sorted(
        verdicts, key=lambda verdict: (verdict.step, verdict.name, *_order(verdict))
    )
    for (step, name), grouped in groupby(
        ordered, key=lambda verdict: (verdict.step, verdict.name)
    ):
        group = list(grouped)
        feedback = [verdict for verdict in group if verdict.kind == "feedback"]
        expected = [verdict for verdict in group if verdict.kind == "expectation"]
        said: list[str] = []
        if feedback:
            yes = sum(1 for verdict in feedback if verdict.value is True)
            no = sum(1 for verdict in feedback if verdict.value is False)
            said.append(f"{yes} yes · {no} no")
        if expected:
            said.append(f"{len(expected)} value{'' if len(expected) == 1 else 's'} expected")
        lines.append(f"{step}  {name}  {' · '.join(said)}")
        for verdict in feedback:
            if verdict.value is True:
                continue
            reason = verdict.rationale or "no reason given"
            if verdict.value is not False:
                reason = f"{verdict.value!r} -- {reason}"
            lines.append(f"    {verdict.document}  {verdict.reviewer}: {reason}")
    return lines


@dataclass(frozen=True)
class Candidate:
    """A value a reviewer expected, waiting for a maintainer to make it gold (R15.4).

    `suggested_by` is the author as MLflow recorded it, which is `User` for the
    trace view. It is provenance, kept in the gold entry's reason; the answer
    itself is signed by the maintainer who applies it (R7.7).
    """

    document: str
    field: str
    value: object
    suggested_by: str
    at: str
    trace: str
    reason: str | None

    __hash__ = None  # type: ignore[assignment]


class CandidatesRefused(ValueError):
    """Candidates that cannot become gold, every one of them named (R15.4 rows 5-7).

    All at once rather than the first: a maintainer fixes the file once, and a
    gold set half-applied is a definition of correct nobody agreed to.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def candidates_of(verdicts: Sequence[Verdict]) -> list[Candidate]:
    """Every expected value, as a candidate; never a feedback (R15.4 row 1).

    A thumbs-down says an answer is wrong and not what is right, so it is the
    report's alone. Sorted by document, field and when, as the file is read.
    """
    found = [
        Candidate(
            document=verdict.document,
            field=verdict.name,
            value=verdict.value,
            suggested_by=verdict.reviewer,
            at=verdict.at,
            trace=verdict.trace,
            reason=verdict.rationale,
        )
        for verdict in verdicts
        if verdict.kind == "expectation"
    ]
    return sorted(found, key=lambda each: (each.document, each.field, each.at, each.trace))


def candidates_jsonl(candidates: Sequence[Candidate]) -> str:
    """The candidates file: one JSON object per line, keys sorted, a maintainer's to edit."""
    return "".join(
        json.dumps(asdict(candidate), sort_keys=True, ensure_ascii=False) + "\n"
        for candidate in candidates
    )


def read_candidates(text: str) -> list[Candidate]:
    """The candidates file as a maintainer left it (R15.4 row 8).

    A line that is not a candidate is refused by its number: the file is
    edited by hand, and "invalid JSON" with no line is a search.
    """
    read: list[Candidate] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            read.append(Candidate(**json.loads(line)))
        except (ValueError, TypeError) as error:
            raise ValueError(
                f"line {number} of {CANDIDATES} is not a candidate: {error}"
            ) from None
    return read


def check_candidates(
    candidates: Sequence[Candidate],
    *,
    kinds: Mapping[str, FieldKind],
    allowed: Mapping[str, Sequence[str]],
) -> list[Candidate]:
    """The candidates that can become gold, one per document and field, or every reason not.

    Refused: a field the pipeline does not declare, which is a verdict about the
    whole answer (row 6); a value an enum does not allow (row 7); a value that is
    not a scalar, which no gold answer is; and two reviewers expecting different
    values for one field of one document (row 5), named with who and where, for
    a maintainer to settle. Two expecting the same value are one candidate, the
    earlier.
    """
    problems: list[str] = []
    for candidate in candidates:
        where = f"{candidate.document} {candidate.field}"
        if candidate.field not in kinds:
            problems.append(
                f"{where}: {candidate.field} is not a field the pipeline declares; a verdict "
                "about the whole answer is the report's, never gold's"
            )
        elif not isinstance(candidate.value, str | int | float | bool | type(None)):
            problems.append(
                f"{where}: {candidate.value!r} is not a value a gold answer can hold; "
                "expect text, a number, yes or no, or nothing"
            )
        elif kinds[candidate.field] is FieldKind.ENUM and candidate.value not in allowed.get(
            candidate.field, ()
        ):
            problems.append(
                f"{where}: {candidate.value!r} is not one of "
                f"{', '.join(allowed.get(candidate.field, ()))}"
            )

    kept: dict[tuple[str, str], Candidate] = {}
    ordered = sorted(
        candidates, key=lambda each: (each.document, each.field, each.at, each.trace)
    )
    for (document, field), grouped in groupby(
        ordered, key=lambda each: (each.document, each.field)
    ):
        group = list(grouped)
        values = {json.dumps(each.value, sort_keys=True) for each in group}
        if len(values) > 1:
            said = ", ".join(
                f"{each.value!r} ({each.suggested_by}, {each.trace})" for each in group
            )
            problems.append(f"{document} {field}: reviewers expected different values: {said}")
        kept[(document, field)] = group[0]

    if problems:
        raise CandidatesRefused(problems)
    return [kept[key] for key in sorted(kept)]


def correction_of(candidate: Candidate, *, verified_by: str, today: date) -> Correction:
    """The correction a maintainer's signature makes of a candidate (R15.4 row 2, R7.7).

    Signed by the maintainer, on the day they applied it: the author MLflow
    recorded is `User` for everyone who used the trace view, and a gold answer
    is signed by a person who can be asked about it. Where it was expected, and
    by whom as recorded, is kept in the reason.
    """
    reason = (
        f"expected by {candidate.suggested_by} on {candidate.at[:10]} "
        f"in MLflow trace {candidate.trace}"
    )
    if candidate.reason:
        reason += f": {candidate.reason}"
    return Correction(
        field=candidate.field,
        value=candidate.value,
        verified_by=verified_by,
        verified_at=today,
        reason=reason,
    )
