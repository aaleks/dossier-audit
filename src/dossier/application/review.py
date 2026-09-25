"""Bringing reviewers' verdicts back from MLflow (spec 015).

`pull_reviews` asks a `ReviewSource` for every verdict a person left on a
pipeline's runs and writes them where a maintainer reads them: files under
`review/<pipeline>/`, which no run, plan, replay, eval or calibration reads
(R15.5). It asks no model and touches no key, manifest or gold file.
"""

from __future__ import annotations

from pathlib import Path

from dossier.domain.ports import ReviewSource
from dossier.domain.review import FEEDBACK, Verdict, feedback_jsonl

__all__ = ["pull_reviews"]


def pull_reviews(source: ReviewSource, *, experiment: str, directory: Path) -> list[Verdict]:
    """Write every verdict on the runs in `experiment` to `directory`, and return them.

    The whole set each time, not what is new since the last pull: the file is
    the state of the review, and `git diff` is what says what changed (R15.3
    row 4). No verdict writes nothing -- an empty file would read as a review
    that found nothing to say, which is a different thing from no review.
    """
    verdicts = source.human_verdicts(experiment=experiment)
    if not verdicts:
        return []
    directory.mkdir(parents=True, exist_ok=True)
    (directory / FEEDBACK).write_bytes(feedback_jsonl(verdicts).encode("utf-8"))
    return list(verdicts)
