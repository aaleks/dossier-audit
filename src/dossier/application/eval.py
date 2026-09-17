"""Scoring a past run against a gold set (spec 007).

Reads and scores; asks nothing. The run's results arrive already reproduced from
the cache entries it wrote, and every deterministic verdict is a pure function of
them and of the gold files (R7.1, R7.10). A model is reached only on a cache
miss, and scoring is never one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dossier.application.run import StepReport
from dossier.domain.gold import CalibrationCase, GoldDocument, gold_set_hash
from dossier.domain.hashing import content_hash
from dossier.domain.judges import MINIMUM_SAMPLE, Calibration, NotCalibrated
from dossier.domain.keys import JudgeInputs, cache_key, provenance
from dossier.domain.ports import ArtifactStore, Tracker
from dossier.domain.scoring import (
    DocumentScore,
    FieldKind,
    FieldTotal,
    GoldField,
    Verdict,
    overall,
    score_document,
    with_judged,
)
from dossier.domain.tracking import calibration_record, case_tags
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
    withheld: Mapping[str, str] | None = None,
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
    field the caller withheld records no accuracy at all, and the run carries a
    tag naming it and saying why: a metric that is simply absent reads as a
    field nobody verified, which is a different thing and wants different work
    (R7.5, R7.3 row 4).

    `withheld` is handed in rather than worked out here, and that is the point.
    The terminal decides which fields it may report (R7.15); MLflow records the
    same decision rather than reaching it a second way. Computing it twice is
    exactly how the two came to disagree: a recomputation from thresholds alone
    sees nothing wrong with a judge that was never measured or whose calibration
    is stale, so the metric was recorded while the report withheld it. Spec 011
    is explicit -- MLflow is a second place to read a figure, never a second way
    of arriving at one.

    `start_eval` and `finish_eval` are the two halves, because a judge's traces
    have to sit inside the run (R7.18 row 5): the run opens before scoring and
    closes after the totals are known. This is their sum, for an eval that
    judges nothing.
    """
    start_eval(
        tracker,
        experiment=experiment,
        pipeline=pipeline,
        run_id=run_id,
        model=model,
        gold=gold,
        gold_files=gold_files,
        judges=judges,
        withheld=withheld,
    )
    finish_eval(tracker, totals=totals, withheld=withheld)


def start_eval(
    tracker: Tracker,
    *,
    experiment: str,
    pipeline: str,
    run_id: str,
    model: str,
    gold: str,
    gold_files: Mapping[str, bytes],
    judges: Mapping[str, Calibration] | None = None,
    withheld: Mapping[str, str] | None = None,
) -> None:
    """Open the eval's MLflow run with what is known before scoring (R11.3 rows 2-4)."""
    tracker.start_run(
        experiment=experiment,
        name=f"eval of {run_id}",
        tags={
            **tracking_tags(kind="eval", pipeline=pipeline),
            "dossier.run_id": run_id,
            "dossier.gold_hash": gold_set_hash(gold_files),
            **{f"dossier.judge.{field}": why for field, why in (withheld or {}).items()},
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


def finish_eval(
    tracker: Tracker, *, totals: Sequence[FieldTotal], withheld: Mapping[str, str] | None = None
) -> None:
    """Close the eval's run with the figures the report printed (R11.3 rows 1, 4)."""
    # A field whose judge may not be quoted records no accuracy at all -- not its
    # own metric, and not a share of the overall. One list feeds both, so the
    # headline always covers exactly the verdicts the breakdown does. Summing
    # every total here instead would hand back in aggregate the number R7.5 just
    # withheld, in the figure most people read first (R11.3 row 4).
    reportable = [total for total in totals if total.field not in (withheld or {})]
    metrics = {f"accuracy/{total.field}": total.percentage for total in reportable}
    summed = overall(reportable)
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


# The wrapper dossier puts a rubric in: the material and the output format, and
# nothing that adds to the standard the rubric sets. A named constant rather
# than an f-string in a body, because its hash is part of what a calibration
# records (R7.19): an edit here changes what every judge is asked with no byte
# of the author's rubric moving, and `is_stale` has to be able to see it.
JUDGE_PROMPT_TEMPLATE = (
    "{rubric}\n\n"
    "Document {document}, in full:\n"
    "<document>\n{text}\n</document>\n\n"
    "Stated root cause:\n<claim>{answer}</claim>\n\n"
    'Answer with JSON only: {{"supported": true|false, "evidence": "..."}}. '
    "`evidence` is at most two sentences, quoting or naming the part of the "
    "document you relied on."
)


def judge_prompt_hash() -> str:
    """The hash of the wrapper a judge's question is put in (R7.19)."""
    return content_hash(JUDGE_PROMPT_TEMPLATE.encode("utf-8"))


def judge_prompt(*, rubric: str, document: str, text: str, answer: str) -> str:
    """The question put to a judge about one candidate root cause.

    The rubric is passed through as the pipeline author wrote it, and nothing
    here adds to the standard it sets. That is not tidiness: a prompt tuned
    against the calibration sample measures the tuning rather than the judge,
    and the figure it produces is the one a threshold would then be set from
    (R7.11). Everything below the rubric is the material and the output format.
    """
    return JUDGE_PROMPT_TEMPLATE.format(
        rubric=rubric.strip(), document=document, text=text.strip(), answer=answer.strip()
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


# What a cached verdict holds: the boolean a rule asserts and the evidence a
# person reads (R7.18). Sorted keys and no whitespace, so the same verdict is
# the same bytes wherever it was written (R5.5).
def _verdict_bytes(supported: bool, evidence: str) -> bytes:
    return json.dumps(
        {"supported": supported, "evidence": evidence}, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def judged_cached(
    model,
    cache: ArtifactStore,
    *,
    inputs: JudgeInputs,
    rubric: str,
    document: str,
    text: str,
    answer: str,
    run_id: str,
    dossier_version: str,
    tracker: Tracker | None = None,
    field: str = "",
) -> tuple[bool, str]:
    """One judge verdict, served from the cache or asked of the judge on a miss (R7.18).

    A judge is a model, and R0.10 says a model is asked only on a cache miss.
    The verdict is an artifact like any stage's: content-addressed by
    `JudgeInputs` and written with a provenance record, so a second eval of the
    same run asks nothing and a run that changed one document's answer asks
    about that candidate alone. Recorded under the field's name as its step,
    since a judge has no step of its own.

    With a `tracker`, the verdict is one trace on the eval's run, tagged with
    the document and the field, holding an LLM span only when the judge was
    asked (R7.18 row 5, R11.2 row 3's shape): seeing that a verdict cost
    nothing is information.
    """
    if tracker is not None:
        tracker.start_trace(
            name=f"{field} \u00b7 {document}",
            tags={"dossier.document": document, "dossier.field": field},
        )
    try:
        key = cache_key(inputs)
        hit = cache.get(key, require_record=True)
        if hit is not None:
            try:
                verdict = json.loads(hit)
                return bool(verdict["supported"]), str(verdict.get("evidence", ""))
            except (ValueError, KeyError, TypeError):
                # A damaged entry is a miss, not authority (R5.9): the judge is
                # asked again and the entry rewritten below.
                pass
        supported, evidence = judged(
            model, rubric=rubric, document=document, text=text, answer=answer
        )
        if tracker is not None:
            tracker.span(
                kind="llm",
                name=inputs.judge_model,
                attributes={"dossier.model": inputs.judge_model},
            )
        cache.put(
            key,
            _verdict_bytes(supported, evidence),
            record=provenance(
                inputs, run_id=run_id, dossier_version=dossier_version, step="judge"
            ),
        )
        return supported, evidence
    finally:
        if tracker is not None:
            tracker.end_trace(status="OK")


@dataclass(frozen=True)
class Judging:
    """Everything `judge_scores` needs handed to it, and nothing it goes and finds.

    `rubrics` is the eligible fields only -- the ones R7.15 lets be reported --
    mapped to the rubric text and its hash. A field not in it is never judged:
    nothing is measured for a number nobody may quote (R7.17 row 6).
    """

    model: object
    cache: ArtifactStore
    documents: Mapping[str, str]
    rubrics: Mapping[str, tuple[str, str]]
    judge_model: str
    run_id: str
    dossier_version: str
    tracker: Tracker | None = None


def judge_scores(
    scores: Sequence[DocumentScore], *, report: StepReport, judging: Judging
) -> tuple[DocumentScore, ...]:
    """Ask the judge about every deferred, eligible verdict and fold its answers in (R7.17).

    The judge decides only what the deterministic scorers left: a verdict is
    deferred only when gold has a value and the run's value is grounded (R7.3,
    R7.4 decide first), and asked only for a field in `judging.rubrics`. The
    candidate is the run's answer as it produced it, and the document is the
    text the run was shown.
    """
    prompt_hash = judge_prompt_hash()
    records = {
        result.document: {record.field: record for record in result.records}
        for result in report.results
    }
    judged: list[DocumentScore] = []
    for score in scores:
        verdicts: dict[str, tuple[bool, str]] = {}
        for result in score.results:
            if result.verdict is not Verdict.NEEDS_JUDGE or result.field not in judging.rubrics:
                continue
            rubric, rubric_hash = judging.rubrics[result.field]
            candidate = str(records[score.document][result.field].value)
            text = judging.documents[score.document]
            verdicts[result.field] = judged_cached(
                judging.model,
                judging.cache,
                inputs=JudgeInputs(
                    judge_model=judging.judge_model,
                    rubric_hash=rubric_hash,
                    prompt_hash=prompt_hash,
                    document_hash=content_hash(text.encode("utf-8")),
                    candidate_hash=content_hash(candidate.encode("utf-8")),
                ),
                rubric=rubric,
                document=score.document,
                text=text,
                answer=candidate,
                run_id=judging.run_id,
                dossier_version=judging.dossier_version,
                tracker=judging.tracker,
                field=result.field,
            )
        judged.append(with_judged(score, verdicts))
    return tuple(judged)


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

    The model identifier, the rubric hash and the prompt hash travel with the
    figure because an agreement number on its own says a judge agreed with a
    human without saying which judge, or on what question -- and `is_stale`
    needs all three to notice when any has moved since (R7.6, R7.19).
    """
    measured, _ = agreement(verdicts=verdicts, human=human)
    return Calibration(
        judge_model=judge_model,
        rubric_hash=rubric_hash,
        prompt_hash=judge_prompt_hash(),
        agreement=measured,
        sample_size=len(human),
    )


# Where a measurement is kept, beside the gold set it was measured against. A
# subdirectory, so a calibration is not one of the `<document>.json` files the
# gold set is made of, which `_validate_gold` would read as a verified answer
# (R7.14, R3.7 row 1).
CALIBRATIONS_DIR = "calibrations"


def calibrate_field(
    model,
    *,
    directory: Path,
    field: str,
    cases: Sequence[CalibrationCase],
    rubric: str,
    rubric_hash: str,
    documents: Mapping[str, str],
    judge_model: str,
    tracker: Tracker | None = None,
) -> Calibration:
    """Measure a judge against a sample, and write what was measured (R7.14).

    Every input is passed in. The judge client, the sample, the rubric and the
    documents' text are all this function's arguments rather than things it goes
    and finds, which is what lets it be measured against a fake that counts calls
    and what keeps the question of *where* text comes from in the composition
    root (R0.10's shape).

    Refused below the minimum before a single call is made. A sample too small
    cannot produce a figure that means anything (R7.11 row 3), and judging it
    anyway would spend twenty model calls to arrive at a number nobody may quote
    -- then leave a file behind that reads exactly like a calibration.

    Verdicts are keyed by position in the sample. `document` repeats -- two cases
    about `INC-4830` is the ordinary shape, one supported and one planted -- and
    R7.16 treats a record's `id` as bookkeeping it ignores, so the only key that
    is certainly unique is where the record sits.

    With a `tracker`, each case is one trace holding one LLM span, tagged with
    the document and both verdicts (R11.5). The trace is recorded once the
    verdict is in rather than opened before the call, as a run's traces are
    (R11.1): the judge's verdict is a tag, a trace's tags are set when it
    starts, and a calibration trace is exactly one call, so nothing that
    happens inside it goes unrecorded by waiting.
    """
    _require_measurable(field, cases)

    human: dict[str, bool] = {}
    verdicts: dict[str, bool] = {}
    for index, case in enumerate(cases):
        position = str(index)
        human[position] = case.supported
        supported, _ = judged(
            model,
            rubric=rubric,
            document=case.document,
            text=documents[case.document],
            answer=case.answer,
        )
        verdicts[position] = supported
        if tracker is not None:
            tracker.start_trace(
                name=f"{field} · {case.document}",
                tags=case_tags(
                    document=case.document, verified=case.supported, judged=supported
                ),
            )
            tracker.span(
                kind="llm", name=judge_model, attributes={"dossier.model": judge_model}
            )
            tracker.end_trace(status="OK")

    measured = calibration(
        verdicts=verdicts, human=human, judge_model=judge_model, rubric_hash=rubric_hash
    )

    path = directory / CALIBRATIONS_DIR / f"{field}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted and newline-terminated: the file is committed beside the gold set,
    # and a diff should show a figure that moved rather than a key that did.
    path.write_text(
        json.dumps(measured.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return measured


def _require_measurable(field: str, cases: Sequence[CalibrationCase]) -> None:
    """Refuse a sample too small to produce a figure that means anything (R7.11 row 3)."""
    if len(cases) < MINIMUM_SAMPLE:
        raise NotCalibrated(
            f"{field}: the sample holds {len(cases)} case(s), and {MINIMUM_SAMPLE} is the "
            "minimum at which agreement means anything. Report this as not measurable at "
            "this N, never as a percentage (R7.11 example 3)."
        )


@dataclass(frozen=True)
class FieldSample:
    """What one judged field is measured against: its sample and its rubric."""

    cases: Sequence[CalibrationCase]
    rubric: str
    rubric_hash: str


def calibrate_fields(
    model,
    *,
    directory: Path,
    samples: Mapping[str, FieldSample],
    documents: Mapping[str, str],
    judge_model: str,
    tracker: Tracker | None = None,
    experiment: str = "",
    pipeline: str = "",
    gold_files: Mapping[str, bytes] | None = None,
) -> dict[str, Calibration]:
    """Measure every judged field, as one MLflow run when there is a tracker (R11.5).

    One run per gold set rather than per field, opened around the whole
    measurement so every field's traces land inside it. The params and metrics
    are `calibration_record`'s -- the figures the file holds and the terminal
    prints -- and the run is tagged with the gold set's hash as an eval's is
    (R11.3 row 2): two calibrations against samples that differ by one verdict
    are not comparable.

    Every sample is checked before the run is opened. A short one is refused
    with no judge call made (R7.14 row 3), and a run opened for it would read
    back as a measurement that happened and recorded nothing -- a different,
    and worse, story than "refused" (R11.5 row 4).
    """
    for field, sample in sorted(samples.items()):
        _require_measurable(field, sample.cases)
    if tracker is not None:
        tracker.start_run(
            experiment=experiment,
            name=f"calibration of {directory.name}",
            tags={
                **tracking_tags(kind="calibrate", pipeline=pipeline),
                "dossier.gold_hash": gold_set_hash(gold_files or {}),
            },
        )
    measured: dict[str, Calibration] = {}
    params: dict[str, str] = {}
    metrics: dict[str, float] = {}
    for field, sample in sorted(samples.items()):
        measured[field] = calibrate_field(
            model,
            directory=directory,
            field=field,
            cases=sample.cases,
            rubric=sample.rubric,
            rubric_hash=sample.rubric_hash,
            documents=documents,
            judge_model=judge_model,
            tracker=tracker,
        )
        recorded_params, recorded_metrics = calibration_record(
            field=field, calibration=measured[field]
        )
        params.update(recorded_params)
        metrics.update(recorded_metrics)
    if tracker is not None:
        tracker.log_params(params)
        tracker.log_metrics(metrics)
        tracker.end_run(status="FINISHED")
    return measured


def load_calibration(directory: Path, field: str) -> Calibration | None:
    """What a judge was last measured at, or `None` if it never was (R7.15).

    `None` rather than a raised error, because never measured is a different
    state from measured and found wanting: one wants a `dossier calibrate`, the
    other a better judge or a bar somebody agrees to lower. Collapsing the two
    into "no score" sends a reader to the wrong fix, which is the failure R7.5's
    honest silence exists to avoid.

    A file that is present and malformed is not silence, and is not swallowed:
    pydantic's error travels, as it does for a gold document.
    """
    path = directory / CALIBRATIONS_DIR / f"{field}.json"
    if not path.is_file():
        return None
    return Calibration.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _gold_fields(document: GoldDocument) -> dict[str, GoldField]:
    return {
        name: GoldField(**{key: entry[key] for key in _SCORED_KEYS if key in entry})
        for name, entry in document.fields.items()
    }
