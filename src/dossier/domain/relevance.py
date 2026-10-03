"""How well a search ranked, against what a person judged (spec 022).

Each function reads the document ids a search listed, best first, and a
query's judgments: a grade by document id, 2 for one that answers the question,
1 for one related to it, 0 for one judged and not relevant. A document no
judgment names is unjudged, and gains nothing. No database and no model: the
same ids and judgments give the same measures on every machine.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# The first page: what a person reads of a search, and what the measures read.
CUT = 10


def _gain(grade: int) -> float:
    # Exponential, so "answers it" counts three times "related" (R22.1).
    return 2**grade - 1


def _discounted(grades: Sequence[int]) -> float:
    return sum(_gain(grade) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def ndcg_at(listed: Sequence[str], judged: Mapping[str, int], k: int = CUT) -> float | None:
    """nDCG@k of `listed`, or `None` when nothing is graded 1 or 2 (R22.1, R22.4).

    The gain of the first `k` listed, discounted by rank, over the same sum for
    the best order the judgments allow: the judged documents by grade, highest
    first, the first `k`.
    """
    ideal = sorted((grade for grade in judged.values() if grade > 0), reverse=True)[:k]
    if not ideal:
        return None
    found = _discounted([judged.get(document, 0) for document in listed[:k]])
    return found / _discounted(ideal)


def recall_at(listed: Sequence[str], judged: Mapping[str, int], k: int = CUT) -> float | None:
    """The share of documents graded 1 or 2 in the first `k` listed (R22.2).

    `None` when nothing is graded 1 or 2: a 0 is judged and not relevant, and
    is no document to find.
    """
    relevant = {document for document, grade in judged.items() if grade > 0}
    if not relevant:
        return None
    return len(relevant.intersection(listed[:k])) / len(relevant)


def unjudged(listed: Sequence[str], judged: Mapping[str, int], k: int = CUT) -> int:
    """How many of the first `k` listed no judgment names (R22.3)."""
    return sum(1 for document in listed[:k] if document not in judged)


@dataclass(frozen=True)
class Measured:
    """One query's measures. `ndcg` and `recall` are `None` for a query nothing answers."""

    name: str
    ndcg: float | None
    recall: float | None
    unjudged: int


def measured(name: str, listed: Sequence[str], judged: Mapping[str, int]) -> Measured:
    """The measures of one query, named by its gold file."""
    return Measured(
        name=name,
        ndcg=ndcg_at(listed, judged),
        recall=recall_at(listed, judged),
        unjudged=unjudged(listed, judged),
    )


@dataclass(frozen=True)
class Means:
    """The means over the queries scored, and the ones left out, by name."""

    ndcg: float | None
    recall: float | None
    scored: int
    unscored: tuple[str, ...]


def means(queries: Sequence[Measured]) -> Means:
    """Average the queries scored; name the ones nothing answers (R22.4).

    A query with nothing graded 1 or 2 has no ideal to divide by, and averaging
    it in as 0 would lower the mean for a question nobody judged answerable.
    """
    scored = [query for query in queries if query.ndcg is not None]
    unscored = tuple(query.name for query in queries if query.ndcg is None)
    if not scored:
        return Means(ndcg=None, recall=None, scored=0, unscored=unscored)
    return Means(
        ndcg=sum(query.ndcg for query in scored) / len(scored),
        recall=sum(query.recall or 0.0 for query in scored) / len(scored),
        scored=len(scored),
        unscored=unscored,
    )
