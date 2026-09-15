"""Scoring a past run against a gold set (spec 007).

Reads and scores; asks nothing. The run's results arrive already reproduced from
the cache entries it wrote, and every deterministic verdict is a pure function of
them and of the gold files (R7.1, R7.10). A model is reached only on a cache
miss, and scoring is never one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from dossier.application.run import StepReport
from dossier.domain.gold import GoldDocument, gold_set_hash
from dossier.domain.ports import Tracker
from dossier.domain.scoring import (
    DocumentScore,
    FieldKind,
    FieldTotal,
    GoldField,
    overall,
    score_document,
)
from dossier.domain.tracking import tags as tracking_tags

# What a gold field entry holds that scoring reads. A reviewer's correction also
# records who made it, when, and what it superseded (R7.7) -- the audit trail of
# the answer, which says nothing about whether a run agreed with it.
_SCORED_KEYS = ("value", "currency", "reason")


def load_gold(directory: Path) -> dict[str, GoldDocument]:
    """Every gold file in `directory`, by the document it verifies.

    Keyed by the `document` inside the file rather than by its name: the key is
    what a run reports a document under (R4.10), and a file renamed on disk is
    still the same verified answer.
    """
    documents: dict[str, GoldDocument] = {}
    for path in sorted(directory.glob("*.json")):
        gold = GoldDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        documents[gold.document] = gold
    return documents


def score_run(
    *,
    report: StepReport,
    gold: Mapping[str, GoldDocument],
    kinds: Mapping[str, FieldKind],
) -> tuple[DocumentScore, ...]:
    """Score every document the step produced output for and gold verifies."""
    scores: list[DocumentScore] = []
    for result in report.results:
        if result.failed or result.document not in gold:
            continue
        checks = {
            record.field: check
            for record, check in zip(result.records, result.checks, strict=True)
        }
        scores.append(
            score_document(
                document=result.document,
                records=result.records,
                checks=checks,
                gold=_gold_fields(gold[result.document]),
                kinds=kinds,
            )
        )
    return tuple(scores)


def record_eval(
    tracker: Tracker,
    *,
    experiment: str,
    pipeline: str,
    run_id: str,
    model: str,
    gold: str,
    gold_files: Mapping[str, bytes],
    totals: Sequence[FieldTotal],
) -> None:
    """Record one `dossier eval` as one MLflow run, one metric per scored field (R11.3).

    The metrics are the percentages the report prints -- `75.0`, not `0.75` --
    so the terminal and MLflow cannot disagree. Only scored fields are
    recorded: a field gold never verified has no total, and a 0.0 for it would
    read as a field that was always wrong (R7.3 row 4).

    The gold set is named, and tagged with a hash of its contents, since two
    evals over different gold sets are not comparable; the run it scored is
    tagged by id, so the eval can be followed back to what it measured.
    """
    tracker.start_run(
        experiment=experiment,
        name=f"eval of {run_id}",
        tags={
            **tracking_tags(kind="eval", pipeline=pipeline),
            "dossier.run_id": run_id,
            "dossier.gold_hash": gold_set_hash(gold_files),
        },
    )
    tracker.log_params({"model": model, "gold": Path(gold).name})
    metrics = {f"accuracy/{total.field}": total.percentage for total in totals}
    summed = overall(totals)
    if summed is not None:
        metrics["accuracy/overall"] = summed.percentage
    tracker.log_metrics(metrics)
    tracker.end_run(status="FINISHED")


def _gold_fields(document: GoldDocument) -> dict[str, GoldField]:
    return {
        name: GoldField(**{key: entry[key] for key in _SCORED_KEYS if key in entry})
        for name, entry in document.fields.items()
    }
