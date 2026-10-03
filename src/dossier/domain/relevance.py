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


# What a grade may be: answers it, related, judged and not relevant.
GRADES = (0, 1, 2)


@dataclass(frozen=True)
class RelevanceQuery:
    """One question of a relevance gold set, and what a person judged of it (spec 022).

    `name` is the file's, without `.yaml`: what is printed and recorded for it.
    """

    name: str
    query: str
    readers: tuple[str, ...]
    judged_by: str
    judged: Mapping[str, int]


class UnreadableRelevance(ValueError):
    """Relevance gold that cannot be read as judgments, one line each (R22.5)."""

    def __init__(self, lines: Sequence[str]) -> None:
        self.lines = tuple(lines)
        super().__init__("\n".join(self.lines))


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _document_id(value: object) -> bool:
    # `<source>:<key>`, as the index names a document (spec 018): a key two
    # sources share is not one document. The key may hold a colon of its own.
    if not isinstance(value, str):
        return False
    source, colon, key = value.partition(":")
    return bool(colon) and bool(source.strip()) and bool(key.strip())


def read_relevance(name: str, data: object) -> RelevanceQuery:
    """One relevance gold file, or `UnreadableRelevance` naming each problem (R22.5).

    Refused rather than skipped: a skipped query would leave the means over
    fewer questions than the gold holds, and say nothing.
    """
    file = f"{name}.yaml"
    if not isinstance(data, dict):
        raise UnreadableRelevance(
            [f"{file}: not a mapping of query, readers, judged_by and judged"]
        )
    lines: list[str] = []
    query, readers, judged_by, judged = (
        data.get("query"),
        data.get("readers"),
        data.get("judged_by"),
        data.get("judged"),
    )
    if not _text(query):
        lines.append(f"{file}: query is missing")
    if readers is None:
        # A search names its readers, and a measured one is no exception (R19.11).
        lines.append(f"{file}: readers is missing: a search names its readers (R19.11)")
    elif not (isinstance(readers, list) and readers and all(map(_text, readers))):
        lines.append(f"{file}: readers is not a list of readers")
    if not _text(judged_by):
        lines.append(
            f"{file}: judged_by is missing: there is no anonymous path into gold (R7.7)"
        )
    if not isinstance(judged, dict):
        lines.append(f"{file}: judged is missing: grades 0, 1 or 2 by document id")
    else:
        for document, grade in judged.items():
            if not _document_id(document):
                lines.append(
                    f"{file}: {document} is not a document id: "
                    "a document is named <source>:<key>"
                )
            # `bool` is an `int` to Python, and `true` is no grade.
            elif type(grade) is not int or grade not in GRADES:
                lines.append(f"{file}: {document} is graded {grade!r}; a grade is 0, 1 or 2")
    if lines:
        raise UnreadableRelevance(lines)
    return RelevanceQuery(
        name=name,
        query=str(query),
        readers=tuple(readers),
        judged_by=str(judged_by),
        judged=dict(judged),
    )


def unreadable(
    queries: Sequence[RelevanceQuery], acl: Mapping[str, Sequence[str]]
) -> list[str]:
    """One line for each judgment of a document none of its query's readers may read (R22.6).

    `acl` is each source's readers, by source id. Such a document is never
    listed for those readers (R19.10), so judging it would count a miss the
    search was right to make.
    """
    lines: list[str] = []
    for query in queries:
        for document in query.judged:
            source = document.partition(":")[0]
            if not set(query.readers).intersection(acl.get(source, ())):
                lines.append(
                    f"{query.name}.yaml: {document} is not readable by "
                    f"{' or '.join(query.readers)}"
                )
    return lines


def relevance_document(
    index: str,
    queries: Sequence[tuple[RelevanceQuery, Sequence[str], Sequence[str], Measured]],
    found: Means,
) -> dict[str, object]:
    """A measurement as one object: the means, then each query (R22.7 row 2)."""
    return {
        "index": index,
        "ndcg_at_10": found.ndcg,
        "recall_at_10": found.recall,
        "scored": found.scored,
        "unscored": list(found.unscored),
        "queries": [
            {
                "name": query.name,
                "query": query.query,
                "readers": list(readers),
                "ndcg_at_10": score.ndcg,
                "recall_at_10": score.recall,
                "unjudged": score.unjudged,
                "listed": list(listed),
            }
            for query, readers, listed, score in queries
        ],
    }
