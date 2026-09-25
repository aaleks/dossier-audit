"""Bringing reviewers' verdicts back from MLflow (spec 015).

`pull_reviews` asks a `ReviewSource` for every verdict a person left on a
pipeline's runs and writes them where a maintainer reads them: files under
`review/<pipeline>/`, which no run, plan, replay, eval or calibration reads
(R15.5). It asks no model and touches no key, manifest or gold file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dossier.domain.gold import GoldDocument, apply_correction
from dossier.domain.ports import ReviewSource
from dossier.domain.review import (
    CANDIDATES,
    FEEDBACK,
    Verdict,
    candidates_jsonl,
    candidates_of,
    check_candidates,
    correction_of,
    feedback_jsonl,
    read_candidates,
)
from dossier.domain.scoring import FieldKind

__all__ = ["Applied", "apply_candidates", "pull_reviews"]


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
    # Every expected value as a gold candidate, beside it (R15.4 row 1). The
    # whole set, as the feedback is: a candidate rejected by deleting its line
    # comes back on the next pull, and is rejected for good by deleting or
    # overriding the expectation in MLflow, where it was left.
    candidates = candidates_of(verdicts)
    if candidates:
        (directory / CANDIDATES).write_bytes(candidates_jsonl(candidates).encode("utf-8"))
    else:
        (directory / CANDIDATES).unlink(missing_ok=True)
    return list(verdicts)


@dataclass(frozen=True)
class Applied:
    """One answer a maintainer made gold: what it was, and what it is now."""

    document: str
    field: str
    had: bool
    before: object
    after: object

    __hash__ = None  # type: ignore[assignment]


def apply_candidates(
    *,
    candidates: Path,
    gold: Path,
    kinds: dict[str, FieldKind],
    allowed: dict[str, tuple[str, ...]],
    verified_by: str,
    today: date,
) -> list[Applied]:
    """Merge the candidates file, as the maintainer left it, into the gold set (R15.4).

    Every candidate is checked before a file is written, so a refusal leaves the
    gold set exactly as it was (rows 5-7). Each passes through `apply_correction`
    under the maintainer's name (R7.7); a document with no gold file gets one,
    and a candidate whose value is already gold changes nothing (row 4).
    """
    found = check_candidates(
        read_candidates(candidates.read_text(encoding="utf-8")), kinds=kinds, allowed=allowed
    )
    held: dict[str, tuple[Path, GoldDocument]] = {}
    for path in sorted(gold.glob("*.json")):
        document = GoldDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        held[document.document] = (path, document)

    changed: dict[str, GoldDocument] = {}
    applied: list[Applied] = []
    for candidate in found:
        document = changed.get(candidate.document)
        if document is None and candidate.document in held:
            document = held[candidate.document][1]
        entry = document.fields.get(candidate.field, {}) if document is not None else {}
        if "value" in entry and entry["value"] == candidate.value:
            continue
        if document is None:
            document = GoldDocument(
                document=candidate.document, verified_by=verified_by, verified_at=today
            )
        changed[candidate.document] = apply_correction(
            document,
            correction_of(candidate, verified_by=verified_by, today=today),
            today=today,
        )
        applied.append(
            Applied(
                document=candidate.document,
                field=candidate.field,
                had="value" in entry,
                before=entry.get("value"),
                after=candidate.value,
            )
        )

    for key, document in changed.items():
        path = held[key][0] if key in held else gold / f"{key}.json"
        written = json.dumps(document.model_dump(mode="json"), indent=2, ensure_ascii=False)
        path.write_bytes((written + "\n").encode("utf-8"))
    return applied
