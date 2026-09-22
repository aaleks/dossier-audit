"""Scoring a past run against a gold set (spec 007).

Reads and scores; asks nothing. The run's results arrive already reproduced from
the cache entries it wrote, and every deterministic verdict is a pure function of
them and of the gold files (R7.1, R7.10). A model is reached only on a cache
miss, and scoring is never one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

# Aliased: `field` is what this module calls a column of a gold document, and
# a loop over one shadowing the dataclasses helper is a confusing way to find out.
from dataclasses import dataclass
from dataclasses import field as _default
from pathlib import Path

from dossier.application.run import StepReport
from dossier.domain.gold import CalibrationCase, GoldDocument, gold_set_hash
from dossier.domain.grounding import DESCRIBED, GROUNDED, FieldVerdict, judge_name
from dossier.domain.hashing import content_hash
from dossier.domain.judges import (
    Calibration,
    calibration,
    require_measurable,
)
from dossier.domain.keys import JudgeInputs, cache_key, provenance
from dossier.domain.ports import ArtifactStore, ImagePart, Tracker
from dossier.domain.scoring import (
    DocumentScore,
    FieldDelta,
    FieldKind,
    FieldTotal,
    GoldField,
    Verdict,
    overall,
    regressed_fields,
    score_document,
    with_judged,
)
from dossier.domain.tracking import calibration_record, case_tags, run_name
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
    dataset_stale: bool = False,
    environ: Mapping[str, str] | None = None,
    started: str = "",
    pipeline_hash: str = "",
    label: str = "",
) -> None:
    """Open the eval's MLflow run with what is known before scoring (R11.3 rows 2-4).

    `dataset_stale` says the dataset published for this gold set addresses answers
    other than the ones just scored (R11.7 row 2). A tag rather than a param,
    because it is a property of the run as a whole and because a tag is what a
    person filters a list of runs by -- which is how a stale dataset gets noticed.
    """
    tracker.start_run(
        experiment=experiment,
        name=run_name(
            kind="eval",
            values={
                "pipeline": pipeline,
                "started": started,
                "run_id": run_id,
                "model": model,
                "pipeline_hash": pipeline_hash,
                "gold": Path(gold).name,
                "gold_hash": gold_set_hash(gold_files),
                "label": label,
            },
            environ=environ or {},
        ),
        tags={
            **tracking_tags(kind="eval", pipeline=pipeline, label=label, environ=environ or {}),
            "dossier.run_id": run_id,
            "dossier.gold_hash": gold_set_hash(gold_files),
            **({"dossier.dataset_stale": "true"} if dataset_stale else {}),
            **{f"dossier.judge.{field}": why for field, why in (withheld or {}).items()},
        },
    )
    params = {"model": model, "gold": Path(gold).name}
    # The agreement figure travels with the judge that produced it. A number on
    # its own says a judge agreed with a human without saying which judge or on
    # what question, so two evals under different judges would be read as one
    # measurement -- which is what R7.11 row 2 exists to prevent (R11.3 row 3).
    for field, measured in (judges or {}).items():
        params[f"judge/{field}/agreement"] = str(measured.agreement)
        params[f"judge/{field}/model"] = measured.judge_model
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


# What a judge is shown in place of a transcript when the run read the document
# as pictures (R7.21). Fixed text, and not a rubric: it is the sentence the
# `described` bar was measured with, so editing it asks a different question of
# the same threshold -- which is what R7.19 already calls staleness, and what
# R7.11 refuses to let a prompt do to a figure.
SHOWN_AS_PAGES = (
    "The document is supplied as one image per page, in page order. "
    "Read the pages; there is no text transcript."
)


def record_comparison(
    tracker: Tracker,
    *,
    experiment: str,
    pipeline: str,
    runs: tuple[str, str],
    models: tuple[str, str],
    gold: str,
    gold_files: Mapping[str, bytes],
    rows: Sequence[FieldDelta],
    overalls: tuple[FieldTotal | None, FieldTotal | None],
    dataset_stale: bool = False,
    environ: Mapping[str, str] | None = None,
    started: str = "",
    label: str = "",
) -> None:
    """Record a comparison as one MLflow run of per-field deltas (R11.8, R11.9).

    Opened and closed here, because a comparison has no traces to sit inside it:
    it reproduces both runs from their manifests and caches and asks no model
    (R7.10), so there is no (step, document) unit of work to trace. The two runs
    it reads carry their own traces, recorded when they ran.

    Every figure is one `_compare_runs` prints. MLflow is a second place to read
    a figure, never a second way of arriving at one (spec 011).
    """
    tracker.start_run(
        experiment=experiment,
        name=run_name(
            kind="compare",
            values={
                "pipeline": pipeline,
                "started": started,
                "a": runs[0],
                "b": runs[1],
                "gold": Path(gold).name,
                "gold_hash": gold_set_hash(gold_files),
                "label": label,
            },
            environ=environ or {},
        ),
        tags={
            **tracking_tags(
                kind="compare", pipeline=pipeline, label=label, environ=environ or {}
            ),
            "dossier.gold_hash": gold_set_hash(gold_files),
            # Present and empty when nothing regressed. An absent tag is
            # indistinguishable from a comparison recorded before this rule
            # existed, as an absent `changes.json` is from a sync that never ran
            # (R11.6 row 2).
            "dossier.regressed": ", ".join(regressed_fields(rows)),
            **({"dossier.dataset_stale": "true"} if dataset_stale else {}),
        },
    )
    tracker.log_params(
        {
            "a": runs[0],
            "b": runs[1],
            # Each run's own pin, from its own manifest. A single `model` param
            # would be a claim about both runs that is false in exactly the case
            # the change gate exists for: comparing two models (R7.8).
            "a/model": models[0],
            "b/model": models[1],
            "gold": Path(gold).name,
        }
    )
    metrics: dict[str, float] = {}
    for row in rows:
        if row.before is not None:
            metrics[f"a/{row.field}"] = row.before.percentage
        if row.after is not None:
            metrics[f"b/{row.field}"] = row.after.percentage
        if row.delta is not None:
            metrics[f"delta/{row.field}"] = row.delta
    earlier, later = overalls
    if earlier is not None:
        metrics["a/overall"] = earlier.percentage
    if later is not None:
        metrics["b/overall"] = later.percentage
    if earlier is not None and later is not None:
        metrics["delta/overall"] = later.percentage - earlier.percentage
    tracker.log_metrics(metrics)
    tracker.end_run(status="FINISHED")


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
    parts: Sequence[ImagePart] = (),
) -> tuple[bool, str]:
    """One judge verdict on one candidate, with the evidence it gave.

    Returns the boolean and the evidence separately because they are treated
    differently everywhere: the boolean is compared with a human's and is what a
    rule asserts, the evidence is only ever read by a person.
    """
    reply = model.complete(
        judge_prompt(rubric=rubric, document=document, text=text, answer=answer),
        schema=JUDGE_SCHEMA,
        parts=parts,
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
    parts: Sequence[ImagePart] = (),
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
            model, rubric=rubric, document=document, text=text, answer=answer, parts=parts
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
    # The pages of each document the run read as pictures, for the fields it
    # answered from them (R7.21). A document that has none is a document the
    # judge is shown as text, which is every document there has ever been until
    # a `per_part` step read one.
    parts: Mapping[str, Sequence[ImagePart]] = _default(default_factory=dict)


def judge_scores(
    scores: Sequence[DocumentScore], *, report: StepReport, judging: Judging
) -> tuple[DocumentScore, ...]:
    """Ask the judge about every deferred, eligible verdict and fold its answers in (R7.17).

    The judge decides only what the deterministic scorers left: a verdict is
    deferred only when gold has a value and the run's value is grounded (R7.3,
    R7.4 decide first), and asked only for a field in `judging.rubrics`. The
    candidate is the run's answer as it produced it, and the document is what
    the run was shown -- its text, or its pages where the run read pictures
    (R6.15, R7.21).
    """
    prompt_hash = judge_prompt_hash()
    records = {
        result.document: {record.field: record for record in result.records}
        for result in report.results
    }
    # Which (document, field) the run answered from a picture. Read off the
    # checks the run already produced rather than inferred from a document
    # having no text: those are not the same thing, and one of them is R6.3's
    # failure wearing the other's clothes (R6.15).
    described = {
        result.document: {
            record.field
            for record, check in zip(result.records, result.checks, strict=True)
            if check.verdict is FieldVerdict.DESCRIBED
        }
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

            if result.field in described.get(score.document, ()):
                parts = tuple(judging.parts.get(score.document, ()))
                if not parts:
                    # A field the run answered from a picture, in a workspace
                    # that no longer holds the pages. Judging it against an
                    # empty prompt would produce a verdict about nothing, and
                    # guessing the text would judge different evidence -- so it
                    # is left unscored, which is what a deferred verdict with no
                    # answer already means (R7.21 row 5).
                    continue
                text = SHOWN_AS_PAGES
                # The pages stand where the text hash stands, so a described
                # verdict and a grounded one about the same candidate are two
                # entries and neither serves the other (R7.18, R7.21).
                evidence_hash = content_hash(b"".join(part.data for part in parts))
            else:
                parts = ()
                text = judging.documents[score.document]
                evidence_hash = content_hash(text.encode("utf-8"))

            verdicts[result.field] = judged_cached(
                judging.model,
                judging.cache,
                inputs=JudgeInputs(
                    judge_model=judging.judge_model,
                    rubric_hash=rubric_hash,
                    prompt_hash=prompt_hash,
                    document_hash=evidence_hash,
                    candidate_hash=content_hash(candidate.encode("utf-8")),
                ),
                rubric=rubric,
                document=score.document,
                text=text,
                answer=candidate,
                parts=parts,
                run_id=judging.run_id,
                dossier_version=judging.dossier_version,
                tracker=judging.tracker,
                field=result.field,
            )
        judged.append(with_judged(score, verdicts))
    return tuple(judged)


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
    state: str = GROUNDED,
    parts: Mapping[str, Sequence[ImagePart]] | None = None,
    tracker: Tracker | None = None,
) -> Calibration:
    """Measure a judge against a sample, and write what was measured (R7.14).

    `state` names which judge is being measured, and decides what it is shown:
    the document's text, or its pages with the fixed body R7.21 asks with
    (R7.22). Measuring a state on a prompt it is not asked with would produce a
    figure about nothing, and the bar would then be set from it.

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
    require_measurable(field, len(cases))

    human: dict[str, bool] = {}
    verdicts: dict[str, bool] = {}
    for index, case in enumerate(cases):
        position = str(index)
        human[position] = case.supported
        shown = tuple((parts or {}).get(case.document, ()))
        supported, _ = judged(
            model,
            rubric=rubric,
            document=case.document,
            text=SHOWN_AS_PAGES if state == DESCRIBED else documents[case.document],
            answer=case.answer,
            parts=shown if state == DESCRIBED else (),
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
        verdicts=verdicts,
        human=human,
        judge_model=judge_model,
        rubric_hash=rubric_hash,
        prompt_hash=judge_prompt_hash(),
    )

    path = directory / CALIBRATIONS_DIR / f"{judge_name(field, state)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted and newline-terminated: the file is committed beside the gold set,
    # and a diff should show a figure that moved rather than a key that did.
    path.write_text(
        json.dumps(measured.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return measured


@dataclass(frozen=True)
class FieldSample:
    """What one judged field is measured against: its sample and its rubric."""

    cases: Sequence[CalibrationCase]
    rubric: str
    rubric_hash: str
    # The field this judge answers about. Distinct from the key it is filed
    # under, which is the *judge's* name: one field has two of them once a
    # pipeline can answer from a picture (R7.22).
    field: str = ""
    # Which judge these cases measure (R7.22). `grounded` unless the pipeline
    # has a step that can answer from a picture, in which case there are two
    # samples for the field and this says which is which.
    state: str = GROUNDED


def calibrate_fields(
    model,
    *,
    directory: Path,
    samples: Mapping[str, FieldSample],
    documents: Mapping[str, str],
    judge_model: str,
    parts: Mapping[str, Sequence[ImagePart]] | None = None,
    tracker: Tracker | None = None,
    experiment: str = "",
    pipeline: str = "",
    gold_files: Mapping[str, bytes] | None = None,
    environ: Mapping[str, str] | None = None,
    started: str = "",
    label: str = "",
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
    for name, sample in sorted(samples.items()):
        require_measurable(name, len(sample.cases))
    if tracker is not None:
        tracker.start_run(
            experiment=experiment,
            name=run_name(
                kind="calibrate",
                values={
                    "pipeline": pipeline,
                    "started": started,
                    "gold": directory.name,
                    "gold_hash": gold_set_hash(gold_files or {}),
                    "judge_model": judge_model,
                    "label": label,
                },
                environ=environ or {},
            ),
            tags={
                **tracking_tags(
                    kind="calibrate",
                    pipeline=pipeline,
                    label=label,
                    environ=environ or {},
                ),
                "dossier.gold_hash": gold_set_hash(gold_files or {}),
            },
        )
    measured: dict[str, Calibration] = {}
    params: dict[str, str] = {}
    metrics: dict[str, float] = {}
    for name, sample in sorted(samples.items()):
        measured[name] = calibrate_field(
            model,
            directory=directory,
            field=sample.field or name,
            cases=sample.cases,
            rubric=sample.rubric,
            rubric_hash=sample.rubric_hash,
            documents=documents,
            judge_model=judge_model,
            state=sample.state,
            parts=parts,
            tracker=tracker,
        )
        recorded_params, recorded_metrics = calibration_record(
            field=name, calibration=measured[name]
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
