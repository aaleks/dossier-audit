"""Executing a pipeline (spec 004, spec 005).

Two phases, and the order between them is the rule. Everything is resolved and
frozen into a manifest first; only then does a stage run. A resolution error
therefore means nothing ran at all, and a half-executed pipeline is never a state
the system can be in (R4.1).

The two failure modes below look alike and are deliberately different:

- **resolution** fails about the *pipeline*. Nothing about the run is
  well-defined, so nothing happens and no run directory appears.
- **execution** fails about one *document*. Everything else is still valid, the
  earlier stages keep their results, and the run says which document failed
  (R6.9).

Collapsing them in either direction is a real bug. One way throws away work that
was correct and expensive; the other ships an audit that quietly covered less
than it claims to have.

Every stage result is cached against the key that describes it, so a second run
over unchanged inputs asks the model nothing (R5.5), and deleting the cache costs
time and changes no answer (R5.9).

Nothing here constructs a model client, opens a connector or reads a clock.
Every one of those arrives as an argument, which is what lets the whole path run
against `FakeModelClient` and lets the tests assert how many calls happened.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from dossier.application.convert import MARKDOWN, convert_inputs
from dossier.application.extract import DocumentResult, run_stage
from dossier.application.manifest import Manifest
from dossier.domain.fields import OutputSchema
from dossier.domain.grounding import check_field
from dossier.domain.hashing import content_hash
from dossier.domain.keys import ArtifactInput, StageInputs, cache_key, provenance
from dossier.domain.pipeline import (
    SOURCE_KEYWORDS,
    PipelineConfig,
    StepConfig,
    validate_references,
    validate_step_ids,
)
from dossier.domain.ports import ArtifactStore, ModelClient, SnapshotReader, Tracker
from dossier.domain.prompts import render
from dossier.domain.resolution import (
    PinnedConverter,
    ResolvedPlan,
    ResolvedStep,
    resolve,
    validate_input_arity,
)
from dossier.domain.schemas import StageOutput
from dossier.domain.store import RESERVED_KEY, output_path, record_path
from dossier.domain.tracking import tags as tracking_tags

# The `document` an aggregate result is reported under (spec 003). An aggregate
# step has no document -- it read all of them -- so naming it after any one would
# be wrong, and leaving it unnamed would give a report no way to say which step a
# failure came from. Reserved: a source may not hold a document called `*`.
AGGREGATE_KEY = RESERVED_KEY


@dataclass(frozen=True)
class StepReport:
    """What one step produced, per document, in document order."""

    step: str
    results: tuple[DocumentResult, ...] = ()

    @property
    def failed(self) -> tuple[DocumentResult, ...]:
        return tuple(result for result in self.results if result.failed)

    @property
    def served_from_cache(self) -> tuple[DocumentResult, ...]:
        """Results that cost no model call.

        `attempts == 0` is the marker, and it is not a convention: a document
        that reached the model was asked at least once, so zero attempts can only
        mean the answer was already known.
        """
        return tuple(
            result for result in self.results if not result.failed and result.attempts == 0
        )


@dataclass(frozen=True)
class RunReport:
    """What a run did, and where it recorded that it did it."""

    run_id: str
    manifest_path: Path
    steps: tuple[StepReport, ...] = field(default_factory=tuple)

    @property
    def failed(self) -> list[tuple[str, str]]:
        """Every (step, document) that produced no usable output.

        A list rather than a count: "three documents failed" is not actionable
        and "extract failed on INC-5044" is (R6.9, R8.6).
        """
        return [
            (report.step, result.document) for report in self.steps for result in report.failed
        ]

    @property
    def cache_hits(self) -> int:
        return sum(len(report.served_from_cache) for report in self.steps)


def execute(
    *,
    workspace: Path,
    pipeline: PipelineConfig,
    pipeline_hash: str,
    documents: Mapping[str, str],
    media_types: Mapping[str, str] | None = None,
    document_text: Mapping[str, str],
    schemas: Mapping[str, OutputSchema | None],
    prompts: Mapping[str, str],
    model: ModelClient,
    cache: ArtifactStore,
    run_id: str,
    started_at: datetime,
    dossier_version: str,
    converters: Sequence[PinnedConverter] | None = None,
    tracker: Tracker | None = None,
    experiment: str | None = None,
    capture: str = "full",
) -> RunReport:
    """Resolve the pipeline, freeze it, then run it.

    Raises `ValueError` if resolution fails, having written nothing and called
    nothing. Returns a report if it succeeded, whatever individual documents did.

    With a `tracker`, the run is also recorded to `experiment`: one MLflow run
    named after `run_id`, one trace per (step, document), and the counts and the
    manifest once the steps are done (R11.1). Recording starts only after
    resolution, so a run that resolution refused records nothing either.
    Tracking observes; nothing it holds is read back into this run (R0.10).
    """
    if tracker is not None and not experiment:
        raise ValueError("a tracker records to an experiment, and none was named")
    prompt_hashes, schema_hashes = key_hashes(pipeline, prompts=prompts, schemas=schemas)
    plan = _resolve(
        pipeline=pipeline,
        pipeline_hash=pipeline_hash,
        documents=documents,
        media_types=media_types,
        prompt_hashes=prompt_hashes,
        schema_hashes=schema_hashes,
        # And what the model is shown, beside it: a change to dossier's own
        # generator moves no byte of the declaration (R6.12).
        generated_schema_hashes={
            step.id: _generated_schema_hash(schemas.get(step.id)) for step in pipeline.steps
        },
        converters=converters,
    )

    # Only now does anything touch the disk. Every check that could refuse this
    # run has already refused it.
    manifest = Manifest(
        run_id=run_id,
        started_at=started_at,
        dossier_version=dossier_version,
        plan=plan,
    ).write(workspace / "runs")

    keys = [document.key for document in plan.documents]
    declared = {step.id: step for step in pipeline.steps}
    steps: list[StepReport] = []

    # What each earlier step produced, per document, for the prompts below it.
    # Held here rather than read back out of the cache, so a cache that vanishes
    # mid-run cannot strand a later stage (R5.9 example 3).
    produced: dict[str, dict[str, str]] = {}

    if tracker is not None:
        tracker.start_run(
            experiment=experiment or "",
            name=run_id,
            tags=tracking_tags(kind="run", pipeline=pipeline.name),
        )
        tracker.log_params(
            {
                "pipeline": pipeline.name,
                "model": plan.model,
                "pipeline_hash": plan.pipeline_hash,
            }
        )

    try:
        for step in plan.steps:
            over = [AGGREGATE_KEY] if declared[step.id].mode == "aggregate" else keys
            output = schemas.get(step.id)
            results: list[DocumentResult] = []
            for key in over:
                # A document an earlier step produced nothing for is skipped,
                # not run with an empty input: that would ask a model about a
                # document nobody read and cache the answer under a key whose
                # input hash is the hash of `""` -- invisible in the provenance
                # record, and served again next run (R6.13, R5.5). It already
                # failed once, at the step that could not produce its output.
                if declared[step.id].mode != "aggregate" and _missing_input(
                    declared=declared[step.id],
                    resolved=step,
                    document=key,
                    produced=produced,
                ):
                    continue

                # One trace per (step, document): the unit of a cache key, so one
                # trace is one key computed or served (spec 011). Opened before
                # the work, so what happens inside it is recorded inside it.
                if tracker is not None:
                    tracker.start_trace(
                        name=f"{step.id} · {key}",
                        tags={"dossier.step": step.id, "dossier.document": key},
                    )
                result, stage_key = _run_one(
                    step=step,
                    declared=declared[step.id],
                    document=key,
                    documents=keys,
                    document_text=document_text,
                    produced=produced,
                    schema=None if output is None else output.schema,
                    prompt=prompts[step.id],
                    model=model,
                    cache=cache,
                    run_id=run_id,
                    dossier_version=dossier_version,
                    tracker=tracker,
                    capture=capture,
                )
                if tracker is not None:
                    tracker.end_trace(
                        status="ERROR" if result.failed else "OK", error=result.error
                    )
                results.append(result)
                # Written now, not when the run ends: a run killed in `verify`
                # still leaves `extract/` complete for the person who opens it
                # (R0.11 row 3). A failed document leaves nothing -- there is no
                # artifact to copy, and nothing may stand in for one (row 4).
                if not result.failed:
                    _publish(
                        run_dir=manifest.parent,
                        step=step.id,
                        document=key,
                        structured=output is not None,
                        payload=_as_text(result).encode(),
                        record=cache.record(stage_key),
                    )
            steps.append(StepReport(step=step.id, results=tuple(results)))
            produced[step.id] = {
                result.document: _as_text(result) for result in results if not result.failed
            }
    except BaseException:
        # A run that stopped -- an unreachable model, an interrupt -- is recorded
        # as failed rather than left looking as if it were still running.
        if tracker is not None:
            tracker.end_run(status="FAILED")
        raise

    report = RunReport(run_id=run_id, manifest_path=manifest, steps=tuple(steps))
    if tracker is not None:
        # The figures the command already knows and prints; MLflow is a second
        # place to read them, never a second way of computing them (spec 011).
        tracker.log_metrics(
            {
                "documents": len(plan.documents),
                "cache_hits": report.cache_hits,
                "model_calls": sum(
                    result.attempts for done in report.steps for result in done.results
                ),
                "failed": len(report.failed),
            }
        )
        tracker.log_artifact(manifest.name, manifest.read_bytes())
        tracker.end_run(status="FAILED" if report.failed else "FINISHED")
    return report


def _as_text(result: DocumentResult) -> str:
    """One step's output: the artifact it is cached as, and the text below it reads.

    Serialised from the validated records rather than from the model's raw reply,
    so a cache hit and a fresh run produce the same bytes even where the model
    answered with different whitespace (R5.5).

    A step with no schema has no records to serialise, and its prose is the
    artifact as written -- there is nothing to normalise it against.
    """
    if result.text is not None:
        return result.text
    return StageOutput(document=result.document, fields=list(result.records)).model_dump_json()


def _run_one(
    *,
    step: ResolvedStep,
    declared: StepConfig,
    document: str,
    documents: Sequence[str],
    document_text: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
    schema: dict | None,
    prompt: str,
    model: ModelClient,
    cache: ArtifactStore,
    run_id: str,
    dossier_version: str,
    tracker: Tracker | None = None,
    capture: str = "full",
) -> tuple[DocumentResult, str]:
    """One (step, document), served from cache or asked of the model.

    The key covers the prompt *template*, the schema, the model identifier and
    the hashes of the inputs this stage actually reads -- not the rendered
    prompt. The rendered prompt contains the document, which would make the input
    hashes redundant while hiding what they cover (spec 005).
    """
    values = _input_values(
        declared=declared,
        resolved=step,
        document=document,
        documents=documents,
        aggregate=declared.mode == "aggregate",
        document_text=document_text,
        produced=produced,
    )
    key_inputs = StageInputs(
        step=step.id,
        prompt=ArtifactInput(role="prompt", path=declared.prompt, hash=step.prompt_hash),
        output_schema=(
            None
            if step.schema_hash is None
            else ArtifactInput(role="schema", path=declared.output or "", hash=step.schema_hash)
        ),
        generated_schema=step.generated_schema_hash,
        model=model.model_id,
        inputs=[
            ArtifactInput(
                role=name, path=f"{name}/{document}", hash=content_hash(text.encode())
            )
            for name, text in sorted(values.items())
        ],
    )
    key = cache_key(key_inputs)

    hit = cache.get(key, require_record=True)
    if hit is not None:
        served = _from_cache(
            document=document,
            payload=hit,
            document_text=document_text,
            structured=schema is not None,
        )
        # A damaged entry is a miss, not authority. The cache is an optimisation
        # and never a source of truth (R5.9), so the work is simply redone and
        # the entry is rewritten below -- otherwise one corrupt file would be
        # permanently fatal to a workspace whose inputs are all still present.
        if served is not None:
            _stage_span(tracker, step.id, key, cache="hit")
            return served, key

    _stage_span(tracker, step.id, key, cache="miss")
    result = run_stage(
        document=document,
        prompt=render(prompt, values),
        schema=schema,
        model=model,
        input_documents=document_text,
        tracker=tracker,
        capture=capture,
        # What a span may say under `hashes` (R10.8 row 2): the template, the
        # inputs and the key -- the same three the cache key is made of, so a
        # span with no text still says exactly which question was asked.
        hashes={
            "prompt": step.prompt_hash,
            "inputs": [entry.hash for entry in key_inputs.inputs],
            "key": key,
        },
    )

    if not result.failed:
        # A failed document is deliberately not cached. It is a recorded
        # per-document failure rather than a computed artifact, and caching it
        # would make one bad afternoon permanent (R6.1, R6.9, R5.8 row 4).
        cache.put(
            key,
            _as_text(result).encode(),
            record=provenance(
                key_inputs,
                run_id=run_id,
                dossier_version=dossier_version,
                step=step.id,
                attempts=result.attempts,
            ),
        )
    # The key travels with the result so the caller can put the same bytes and
    # the same record where a person reads them (R0.11) without recomputing it.
    return result, key


def _publish(
    *,
    run_dir: Path,
    step: str,
    document: str,
    structured: bool,
    payload: bytes,
    record: dict | None,
) -> None:
    """Put one artifact and its record under `runs/<run_id>/` (R0.11).

    The bytes are the cache entry's, not a re-rendering: a person opening
    `extract/INC-4821.json` reads exactly what the next step was shown. The
    record is serialised as the cache serialises it, so the two siblings match
    byte for byte (R0.3). Nothing here is ever read back -- `runs/` is a copy for
    a person, and the cache stays the only authority (row 6).
    """
    name = output_path(step, document, structured=structured)
    target = run_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    if record is not None:
        (run_dir / record_path(name)).write_bytes(
            json.dumps(record, sort_keys=True, indent=2).encode("utf-8")
        )


def _stage_span(tracker: Tracker | None, step: str, key: str, *, cache: str) -> None:
    """Which key this (step, document) was, and whether it was served (R11.2).

    Recorded for a hit as for a miss: seeing that a document cost nothing is
    information (spec 011), and the key says which stored answer served it.
    """
    if tracker is not None:
        tracker.span(
            kind="stage", name=step, attributes={"dossier.cache": cache, "dossier.key": key}
        )


def _from_cache(
    *,
    document: str,
    payload: bytes,
    document_text: Mapping[str, str],
    structured: bool = True,
) -> DocumentResult | None:
    """Rebuild what a cached artifact stands for, with no model call.

    Grounding is re-derived rather than stored alongside. It is a pure function
    of the artifact and the documents (R6.4), so re-deriving costs microseconds
    and removes a second thing that could go stale.
    """
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if not structured:
        return DocumentResult(document=document, attempts=0, text=text)

    try:
        output = StageOutput.model_validate_json(text)
    except (ValidationError, ValueError):
        # An entry that is present and unreadable. `None` rather than an
        # exception, because the right answer differs by caller and neither
        # should be decided here: `execute` can recompute, a replay cannot
        # (R5.9, R4.7).
        return None
    checks = tuple(
        check_field(record, input_documents=document_text) for record in output.fields
    )
    return DocumentResult(
        document=document,
        records=tuple(output.fields),
        checks=checks,
        attempts=0,
        # The stored bytes travel on rather than being re-derived from the
        # records. They are the same bytes for every document that shares this
        # key, and two documents with identical content do share one -- so
        # re-serialising under *this* document's name would hand the next step
        # something the cache never held, and change its key (R5.5, R5.7 row 4).
        text=payload.decode(),
    )


def _missing_input(
    *,
    declared: StepConfig,
    resolved: ResolvedStep,
    document: str,
    produced: Mapping[str, Mapping[str, str]],
) -> bool:
    """Whether this step reads something no earlier step produced for `document` (R6.13).

    Only what earlier *steps* produced. `documents` and `reference` are the run's
    own inputs, pinned by resolution, and a document missing from those never
    reaches this loop at all.

    Never asked of an aggregate step: it reads a set, and a member absent from
    the set is not a missing input -- skipping it would throw away the documents
    that did work (R6.13 row 4).
    """
    return any(
        document not in produced.get(target, {})
        for target in _targets(declared, resolved)
        if target not in SOURCE_KEYWORDS
    )


def _input_values(
    *,
    declared: StepConfig,
    resolved: ResolvedStep,
    document: str,
    documents: Sequence[str],
    aggregate: bool,
    document_text: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """What each declared input holds, for this call.

    Keyed by the name the *prompt* uses, which is the name as declared -- sugar
    included, because that is the form R3.6 checked at load time. The resolved
    ids say where the content comes from.

    In a `per_file` step each value is one document's text. In an `aggregate`
    step it is every document, each wrapped in a tag naming its key (spec 003).
    """
    values: dict[str, str] = {}
    for name, target in zip(declared.inputs, _targets(declared, resolved), strict=True):
        source = document_text if target in SOURCE_KEYWORDS else produced.get(target, {})
        if aggregate:
            values[name] = _joined(source, documents)
        else:
            values[name] = source.get(document, "")
    return values


def _joined(source: Mapping[str, str], documents: Sequence[str]) -> str:
    """Every document's content, wrapped in a tag naming its key (spec 003).

    Wrapped rather than concatenated: a model asked to attribute a finding needs
    to know which document it read it in, and R6.4 will not ground a field whose
    `source.document` names nothing.

    Sorted here as well as in `resolve`, which already orders the plan's
    documents -- so this sort is defence in depth rather than the thing making
    the prompt deterministic, and no test kills it on its own. It is kept because
    the function is then correct on its own terms: whatever order a caller passes,
    the same set of documents produces the same prompt and the same key (R0.4,
    R5.6).

    A document the step produced nothing for is absent rather than empty: a blank
    `<document>` invites an answer about a document nobody read.
    """
    return "\n".join(
        f'<document key="{key}">{source[key]}</document>'
        for key in sorted(documents)
        if key in source
    )


def _targets(declared: StepConfig, resolved: ResolvedStep) -> list[str]:
    """The resolved id behind each declared input, positionally.

    A plain lookup. That the two lists are the same length is settled during
    resolution by `validate_input_arity`, which is where a refusal is still free
    -- it used to be discovered here, after the manifest was written and after
    earlier steps had spent model calls (R4.1).
    """
    return list(resolved.inputs)


def key_hashes(
    pipeline: PipelineConfig,
    *,
    prompts: Mapping[str, str],
    schemas: Mapping[str, OutputSchema | None],
) -> tuple[dict[str, str], dict[str, str | None]]:
    """The prompt and declaration hashes a stage key is made of, per step.

    One derivation for both a run and a plan (R4.12): a plan resolved from any
    other would print `cached` for a step the run is about to miss on. The
    declaration's own text is hashed, not the schema generated from it, because
    the generated schema names fields and nothing else (R6.11).
    """
    return (
        {step: content_hash(text.encode()) for step, text in prompts.items()},
        {step.id: _declaration_hash(schemas.get(step.id)) for step in pipeline.steps},
    )


def _declaration_hash(output: OutputSchema | None) -> str | None:
    """The hash a step's declaration puts in its key, or `None` where none was declared.

    `None` rather than the hash of nothing: a step with no declaration is a
    different thing from one whose declaration happens to be empty, and R3.10
    lets an aggregate step be the former.
    """
    return None if output is None else output.declaration_hash


def _generated_schema_hash(output: OutputSchema | None) -> str | None:
    """The hash of the schema a step's model is shown, or `None` where it has none (R6.12)."""
    return None if output is None else output.generated_schema_hash


def _resolve(
    *,
    pipeline: PipelineConfig,
    pipeline_hash: str,
    documents: Mapping[str, str],
    media_types: Mapping[str, str] | None = None,
    prompt_hashes: Mapping[str, str] | None = None,
    schema_hashes: Mapping[str, str | None] | None = None,
    generated_schema_hashes: Mapping[str, str | None] | None = None,
    converters: Sequence[PinnedConverter] | None = None,
) -> ResolvedPlan:
    """Every check that can refuse a run, run before a run exists.

    `validate_step_ids` and `validate_references` are repeated here even though
    `load_pipeline` already ran them. That is not belt and braces: a pipeline can
    reach this function from a replay or from a caller that never touched YAML,
    and R4.1 is a claim about *this* phase rather than about how the config
    happened to arrive.
    """
    validate_step_ids(pipeline)
    validate_references(pipeline)
    plan = resolve(
        pipeline=pipeline,
        pipeline_hash=pipeline_hash,
        documents=documents,
        media_types=media_types,
        prompt_hashes=prompt_hashes,
        schema_hashes=schema_hashes,
        generated_schema_hashes=generated_schema_hashes,
        converters=converters,
    )
    # Every remaining check that could refuse this run, run while refusing it is
    # still free (R4.1).
    validate_input_arity(pipeline.steps, plan.steps)
    return plan


class MissingFromReplay(FileNotFoundError):
    """A replay needs something the workspace no longer holds.

    A replay may fail. What it may never do is quietly substitute other content
    and present the result as the original run (R4.7 example 4), so whatever is
    missing is named.
    """


def replayed_inputs(
    manifest: Manifest, *, store: SnapshotReader, cache: ArtifactStore
) -> dict[str, str]:
    """The converted text a past run read, from the entries it wrote (R4.7).

    Every snapshot the run read must still be held, even though the bytes are
    not needed: a replay that succeeded while the documents it audited were
    gone would reproduce a finding whose evidence no longer exists (R4.9).
    Snapshots are never deleted (R0.2), so a missing one means the workspace
    is damaged, and naming the hash is what makes that diagnosable.

    Each conversion's key is recomposed from the manifest alone -- the pinned
    snapshot, and the id and version of the converter that claimed that
    document's media type -- through the same composition that wrote it.
    Nothing is read from the ledger, from `pipeline.yaml`, or from the
    converters installed today. An entry that is gone, or that has no
    provenance record (an interrupted write, R5.8), stops the replay by name:
    re-deriving it would mean converting with whatever is installed now, which
    is precisely the substitution R4.7 row 4 forbids.
    """
    missing = [
        f"  {document.key}: no snapshot for {document.snapshot[:12]}..."
        for document in manifest.plan.documents
        if not store.exists(document.snapshot)
    ]
    if missing:
        raise MissingFromReplay(
            f"{manifest.run_id} cannot be reproduced: its snapshots are not all held\n"
            + "\n".join(missing)
            + "\nSnapshots are never deleted (R0.2); this workspace is damaged."
        )

    claimed = {(c.media_type, c.kind): c for c in manifest.plan.converters}
    text: dict[str, str] = {}
    for document in manifest.plan.documents:
        converter = claimed.get((document.media_type, MARKDOWN))
        if converter is None:
            missing.append(
                f"  {document.key}: no converter recorded for {document.media_type!r}"
            )
            continue
        key = cache_key(
            convert_inputs(
                snapshot=document.snapshot,
                converter_id=converter.id,
                converter_version=converter.version,
            )
        )
        stored = cache.get(key, require_record=True)
        if stored is None:
            missing.append(
                f"  {document.key}: no cached conversion for snapshot "
                f"{document.snapshot[:12]}... by {converter.id} {converter.version}"
            )
            continue
        text[document.key] = stored.decode("utf-8")

    if missing:
        raise MissingFromReplay(
            f"{manifest.run_id} cannot be reproduced:\n"
            + "\n".join(missing)
            + "\nNothing has been substituted."
        )
    return text


def replay(
    *,
    manifest: Manifest,
    document_text: Mapping[str, str],
    cache: ArtifactStore,
    destination: Path | None = None,
) -> RunReport:
    """Reproduce a past run from its frozen manifest (R4.7).

    Takes no model client, no pipeline and no workspace configuration. That is
    not an omission: a replay that *could* reach a model could produce an answer
    the original run never gave, and "touches no network" is a far stronger
    promise when there is nothing to touch it with. Every result comes from the
    cache entry the original run wrote.

    `pipeline.yaml` is not read at all. Whatever it says today -- a step added, a
    model swapped, the file deleted -- the manifest is the only input (R4.7
    examples 2 and 3), and the snapshots it pinned are the only content, however
    the ledger has moved since (R4.9).

    With a `destination`, what was reproduced is written there, named as a run
    names its outputs (R0.11) -- and only once every key has resolved. A
    missing entry raises before anything is written, so a failed replay leaves
    no directory at all: three of four documents beside a manifest pinning four
    would read as a complete run to anyone who did not see the error (R0.12).
    """
    plan = manifest.plan
    keys = [document.key for document in plan.documents]
    steps: list[StepReport] = []
    produced: dict[str, dict[str, str]] = {}
    reproduced: list[tuple[str, str, bool, bytes, dict | None]] = []

    for step in plan.steps:
        over = [AGGREGATE_KEY] if step.mode == "aggregate" else keys
        results: list[DocumentResult] = []
        for document in over:
            result, key = _replay_one(
                step=step,
                document=document,
                documents=keys,
                model=plan.model,
                document_text=document_text,
                produced=produced,
                cache=cache,
            )
            results.append(result)
            reproduced.append(
                (
                    step.id,
                    document,
                    step.schema_hash is not None,
                    _as_text(result).encode(),
                    cache.record(key),
                )
            )
        steps.append(StepReport(step=step.id, results=tuple(results)))
        produced[step.id] = {
            result.document: _as_text(result) for result in results if not result.failed
        }

    if destination is not None:
        for step_id, document, structured, payload, record in reproduced:
            _publish(
                run_dir=destination,
                step=step_id,
                document=document,
                structured=structured,
                payload=payload,
                record=record,
            )

    # No manifest path: a replay reads one and writes none. Reporting a path it
    # did not write would invite someone to diff against a file this run had no
    # hand in.
    return RunReport(run_id=manifest.run_id, manifest_path=Path(), steps=tuple(steps))


def _replay_one(
    *,
    step: ResolvedStep,
    document: str,
    documents: Sequence[str],
    model: str,
    document_text: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
    cache: ArtifactStore,
) -> tuple[DocumentResult, str]:
    """One (step, document), served from the entry the original run wrote.

    The key is recomposed from the manifest and from what the earlier steps of
    *this replay* produced -- never from anything read out of the workspace
    today. It is therefore the same key the original computation used, or the
    entry is not found and the replay says so rather than pretending.
    """
    contents = [
        _replayed_input(
            target=target,
            document=document,
            documents=documents,
            aggregate=step.mode == "aggregate",
            document_text=document_text,
            produced=produced,
        )
        for target in step.inputs
    ]
    key = cache_key(
        StageInputs(
            step=step.id,
            prompt=ArtifactInput(role="prompt", path=step.id, hash=step.prompt_hash),
            output_schema=(
                None
                if step.schema_hash is None
                else ArtifactInput(role="schema", path=step.id, hash=step.schema_hash)
            ),
            generated_schema=step.generated_schema_hash,
            model=model,
            inputs=[
                ArtifactInput(
                    role=target, path=f"{target}/{document}", hash=content_hash(text.encode())
                )
                for target, text in zip(step.inputs, contents, strict=True)
            ],
        )
    )

    stored = cache.get(key, require_record=True)
    if stored is None:
        raise MissingFromReplay(
            f"step {step.id!r} has no cached artifact for {document!r} "
            f"at {key[:12]}...; this run cannot be reproduced from this "
            "workspace, and nothing has been substituted for it."
        )

    served = _from_cache(
        document=document,
        payload=stored,
        document_text=document_text,
        structured=step.schema_hash is not None,
    )
    if served is None:
        # A replay has no model and nowhere to put one. Serving damaged bytes
        # would present something other than what the run produced, and
        # recomputing would be the substitution R4.7 row 4 forbids.
        raise MissingFromReplay(
            f"step {step.id!r} has a cached artifact for {document!r} that cannot "
            f"be read at {key[:12]}...; this run cannot be reproduced from this "
            "workspace, and nothing has been substituted for it."
        )
    return served, key


def _replayed_input(
    *,
    target: str,
    document: str,
    documents: Sequence[str],
    aggregate: bool,
    document_text: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
) -> str:
    """The content behind one resolved input id, for this document.

    The same content `execute` hashed, obtained the same way. `role` and `path`
    do not enter a key (spec 005), so a replay needs the resolved ids and not the
    declared names the prompt used -- which is fortunate, because a manifest
    records the former and the whole point is that it is enough.
    """
    source = document_text if target in SOURCE_KEYWORDS else produced.get(target, {})
    return _joined(source, documents) if aggregate else source.get(document, "")
