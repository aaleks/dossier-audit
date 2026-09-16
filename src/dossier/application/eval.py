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
from dossier.domain.judges import Calibration, is_eligible
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
    judges: Mapping[str, Calibration] | None = None,
    thresholds: Mapping[str, float] | None = None,
) -> None:
    """Record one `dossier eval` as one MLflow run, one metric per scored field (R11.3).

    The metrics are the percentages the report prints -- `75.0`, not `0.75` --
    so the terminal and MLflow cannot disagree. Only scored fields are
    recorded: a field gold never verified has no total, and a 0.0 for it would
    read as a field that was always wrong (R7.3 row 4).

    The gold set is named, and tagged with a hash of its contents, since two
    evals over different gold sets are not comparable; the run it scored is
    tagged by id, so the eval can be followed back to what it measured.

    A judge's measured agreement is recorded as a param beside the model that
    produced it, because the figure means nothing without it (R7.11 row 2). A
    judge that fell short of its configured threshold reports no accuracy for
    its field at all, and the run carries a tag saying so and why: a metric that
    is simply absent reads as a field nobody verified, which is a different
    thing and wants different work (R7.5, R7.3 row 4). The decision itself stays
    `domain.judges.is_eligible` -- nothing here judges a judge.
    """
    # Which fields a judge measured but may not report (R7.5). Computed before
    # the run opens because the reason is a tag, and tags are set when a run
    # starts. The decision is the domain's -- this only records what it returned.
    ineligible: dict[str, str] = {}
    for field, calibration in (judges or {}).items():
        threshold = (thresholds or {}).get(field)
        if threshold is not None and not is_eligible(calibration, threshold=threshold):
            ineligible[field] = (
                f"ineligible: agreement {calibration.agreement} is below the "
                f"configured threshold {threshold}"
            )

    tracker.start_run(
        experiment=experiment,
        name=f"eval of {run_id}",
        tags={
            **tracking_tags(kind="eval", pipeline=pipeline),
            "dossier.run_id": run_id,
            "dossier.gold_hash": gold_set_hash(gold_files),
            **{f"dossier.judge.{field}": why for field, why in ineligible.items()},
        },
    )
    params = {"model": model, "gold": Path(gold).name}
    # The agreement figure travels with the judge that produced it. A number on
    # its own says a judge agreed with a human without saying which judge or on
    # what question, so two evals under different judges would be read as one
    # measurement -- which is what R7.11 row 2 exists to prevent (R11.3 row 3).
    for field, calibration in (judges or {}).items():
        params[f"judge/{field}/agreement"] = str(calibration.agreement)
        params[f"judge/{field}/model"] = calibration.judge_model
    tracker.log_params(params)
    # A field whose judge may not be quoted records no accuracy at all. A number
    # here would read as a measurement, which is the thing R7.5 refuses.
    metrics = {
        f"accuracy/{total.field}": total.percentage
        for total in totals
        if total.field not in ineligible
    }
    summed = overall(totals)
    if summed is not None:
        metrics["accuracy/overall"] = summed.percentage
    tracker.log_metrics(metrics)
    tracker.end_run(status="FINISHED")


# What a judge is asked to return. `supported` is the verdict and the only thing
# any rule asserts (R7.12 row 2); `evidence` exists for the person reading a
# calibration report, who needs to see *why* a judge disagreed with them before
# signing off a threshold. Nothing scores it, and no test asserts its wording.
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}, "evidence": {"type": "string"}},
    "required": ["supported"],
}


def judge_prompt(*, rubric: str, document: str, text: str, answer: str) -> str:
    """The question put to a judge about one candidate root cause.

    The rubric is passed through as the pipeline author wrote it, and nothing
    here adds to the standard it sets. That is not tidiness: a prompt tuned
    against the calibration sample measures the tuning rather than the judge,
    and the figure it produces is the one a threshold would then be set from
    (R7.11). Everything below the rubric is the material and the output format.
    """
    return (
        f"{rubric.strip()}\n\n"
        f"Document {document}, in full:\n"
        f"<document>\n{text.strip()}\n</document>\n\n"
        f"Stated root cause:\n<claim>{answer.strip()}</claim>\n\n"
        'Answer with JSON only: {"supported": true|false, "evidence": "..."}. '
        "`evidence` is at most two sentences, quoting or naming the part of the "
        "document you relied on."
    )


def judged(
    model,
    *,
    rubric: str,
    document: str,
    text: str,
    answer: str,
) -> tuple[bool, str]:
    """One judge verdict on one candidate, with the evidence it gave.

    Returns the boolean and the evidence separately because they are treated
    differently everywhere: the boolean is compared with a human's and is what a
    rule asserts, the evidence is only ever read by a person.
    """
    reply = model.complete(
        judge_prompt(rubric=rubric, document=document, text=text, answer=answer),
        schema=JUDGE_SCHEMA,
    )
    try:
        verdict = json.loads(reply)
    except json.JSONDecodeError as error:
        raise ValueError(f"the judge answered with no JSON object: {error}") from None
    if not isinstance(verdict, dict) or not isinstance(verdict.get("supported"), bool):
        raise ValueError(f"the judge answered with no `supported` boolean: {reply[:200]!r}")
    return verdict["supported"], str(verdict.get("evidence", ""))


def agreement(
    *, verdicts: Mapping[str, bool], human: Mapping[str, bool]
) -> tuple[float, tuple[str, ...]]:
    """What proportion of the sample the judge and the reviewer agreed on, and where not.

    Over the cases the reviewer scored, which is the sample R7.11 measures. A
    case the judge could not be asked about is absent from `verdicts` and counts
    as a disagreement rather than being dropped: a judge that fails on the hard
    half of a corpus and is scored on the rest would report a figure the corpus
    does not support.
    """
    if not human:
        raise ValueError("no human-scored cases: there is nothing to agree with")

    disagreed = tuple(case for case in sorted(human) if verdicts.get(case) is not human[case])
    agreed = len(human) - len(disagreed)
    return agreed / len(human), disagreed


def calibration(
    *,
    verdicts: Mapping[str, bool],
    human: Mapping[str, bool],
    judge_model: str,
    rubric_hash: str,
) -> Calibration:
    """The measurement, recorded with what it was made against (R7.11 row 2).

    The model identifier and the rubric hash travel with the figure because an
    agreement number on its own says a judge agreed with a human without saying
    which judge, or on what question -- and `is_stale` needs both to notice when
    either has moved since (R7.6).
    """
    measured, _ = agreement(verdicts=verdicts, human=human)
    return Calibration(
        judge_model=judge_model,
        rubric_hash=rubric_hash,
        agreement=measured,
        sample_size=len(human),
    )


def _gold_fields(document: GoldDocument) -> dict[str, GoldField]:
    return {
        name: GoldField(**{key: entry[key] for key in _SCORED_KEYS if key in entry})
        for name, entry in document.fields.items()
    }
