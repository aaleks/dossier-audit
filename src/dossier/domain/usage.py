"""What an answer cost, in tokens, and what several answers cost together.

Each provider says it in its own words (R9.18); the clients read those and hand
the counts back on the reply. Everything that decides what a count *is* -- which
values are counts, what an unreported one means, how several add up -- is here,
so the three clients and the run above them cannot disagree about it.

A count nobody gave is `None`, and it stays `None` through every sum it enters:
a total over the answers that reported would read as the whole (R5.11 row 5).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Tokens:
    """Tokens in and out: what one answer, or several together, cost."""

    input: int | None = None
    output: int | None = None


def counted(value: object) -> int | None:
    """`value` if it is a count of tokens, otherwise `None` (R9.18 row 5).

    A count is a non-negative whole number. `True` is an `int` to Python and is
    refused all the same: a provider that answered a boolean has counted nothing.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def tokens_of(answer: str) -> Tokens:
    """What `answer` says it cost -- nothing, for a plain `str` (R9.18 row 6)."""
    return Tokens(
        input=getattr(answer, "input_tokens", None),
        output=getattr(answer, "output_tokens", None),
    )


def total(each: Iterable[Tokens]) -> Tokens:
    """What several answers cost together: their sums, side by side (R5.11).

    A side any answer did not report is `None` for the whole: a total over the
    answers that did report would read as the whole, and be smaller than what
    was spent. No answers at all cost nothing, which is a count -- `0` -- and
    not an absence of one.
    """
    counts = list(each)
    return Tokens(
        input=_sum([tokens.input for tokens in counts]),
        output=_sum([tokens.output for tokens in counts]),
    )


def _sum(counts: list[int | None]) -> int | None:
    if any(count is None for count in counts):
        return None
    return sum(count for count in counts if count is not None)
