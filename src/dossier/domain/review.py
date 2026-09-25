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
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import groupby
from typing import Literal

__all__ = ["FEEDBACK", "Verdict", "feedback_jsonl", "review_report"]

# Where `dossier review pull` writes every verdict, under `review/<pipeline>/`.
FEEDBACK = "feedback.jsonl"


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
