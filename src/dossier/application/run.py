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
import threading
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from dossier.application.convert import MARKDOWN, convert_inputs
from dossier.application.extract import DocumentResult, run_stage
from dossier.application.manifest import Manifest
from dossier.application.prompts import link_published
from dossier.application.recording import failed_if_stopped
from dossier.domain.conversion import PART_SUFFIX, PART_TYPE, part_name, unpack_parts
from dossier.domain.fields import OutputSchema
from dossier.domain.grounding import FieldCheck, FieldVerdict, check_field, with_derived_page
from dossier.domain.groups import filed_under, group_of
from dossier.domain.hashing import content_hash
from dossier.domain.keys import ArtifactInput, StageInputs, cache_key, provenance
from dossier.domain.pipeline import (
    DEFAULT_INPUT_KIND,
    DOCUMENTS,
    REFERENCE,
    SOURCE_KEYWORDS,
    PipelineConfig,
    SourceConfig,
    StepConfig,
    split_kind,
    validate_modes,
    validate_references,
    validate_step_ids,
)
from dossier.domain.plan import asked_about
from dossier.domain.ports import (
    ArtifactStore,
    ImagePart,
    ModelClient,
    PromptRegistry,
    SnapshotReader,
    Tracker,
    VersionRegistry,
)
from dossier.domain.prompts import prompt_name, render
from dossier.domain.resolution import (
    PinnedConverter,
    ResolvedPlan,
    ResolvedStep,
    check_kinds,
    resolve,
    validate_input_arity,
)
from dossier.domain.schemas import StageOutput
from dossier.domain.store import RESERVED_KEY, output_path, record_path
from dossier.domain.tracking import (
    record_content,
    review_tags,
    run_description,
    run_name,
    step_line,
    token_metrics,
    trace_pages,
    trace_request,
    trace_response,
    unbuilt_tags,
    version_params,
)
from dossier.domain.tracking import tags as tracking_tags
from dossier.domain.usage import Tokens, total
from dossier.domain.versions import version_record

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
    # The per-part results behind `results`, for a `per_part` step (R3.12).
    # Empty for every other step, where a result *is* an artifact. A document is
    # what `results` reports, because that is what a later step reads and what
    # gold verifies; the artifacts are here, because a three-page document
    # produced three of them and a replay that said "1 reproduced" would be
    # describing something that did not happen (R4.14).
    parts: tuple[DocumentResult, ...] = ()
    # What `results` holds one of: a document, or for a `per_group` step a
    # group, which is what its line counts (R3.15 row 1).
    unit: str = "document"

    @property
    def artifacts(self) -> int:
        """How many artifacts this step produced or served."""
        return len(self.parts) or len(self.results)

    @property
    def failed(self) -> tuple[DocumentResult, ...]:
        return tuple(result for result in self.results if result.failed)

    @property
    def tokens(self) -> Tokens | None:
        """What this step's model calls cost in this run, or `None` if it made none (R5.12).

        Only the documents that were asked. One served from cache cost nothing
        in this run, whatever its provenance record says producing it cost
        (R5.11) -- that is the figure a cache exists to keep small. A document
        that failed was asked, twice, and is paid for all the same.
        """
        asked = [result for result in self.results if result.attempts > 0]
        if not asked:
            return None
        return total(result.tokens for result in asked)

    @property
    def served_from_cache(self) -> tuple[DocumentResult, ...]:
        """Results that cost no model call.

        `attempts == 0` is the marker, and it is not a convention: a document
        that reached the model was asked at least once, so zero attempts can only
        mean the answer was already known.
        """
        over = self.parts or self.results
        return tuple(result for result in over if not result.failed and result.attempts == 0)

    @property
    def described(self) -> int:
        """How many fields this step read off a page rather than out of text (R6.15).

        A count rather than the records themselves: it is reported beside
        `failed`, and what a reader needs from it is that the two are different
        numbers. A described field is in neither the grounded total nor the
        failed one, and summing it into either would be the whole point lost.
        """
        return sum(
            1
            for result in self.results
            for check in result.checks
            if check.verdict is FieldVerdict.DESCRIBED
        )

    @property
    def findings(self) -> tuple[tuple[str, FieldCheck], ...]:
        """Every ungrounded or invalid field this step produced, with its document.

        The checks themselves rather than a count, because the reason is the
        point: `check_field` composed a `detail` for a person to read and it
        reached nobody, so a run over sixteen invalid fields printed `0 failed`
        (R6.16). A count alone would repeat that mistake more quietly.

        In `results` order, which is document order, so two runs over one
        workspace report identically (R0.4). A `described` field is not here and
        neither is an abstention: one is counted on its own (R6.15) and the
        other is valid output (R6.5).
        """
        return tuple(
            (result.document, check)
            for result in self.results
            for check in result.field_failures
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


@dataclass(frozen=True)
class RunInputs:
    """What a run is run over: everything that can change what it produces (R0.5).

    The pipeline and what it was loaded with, and the documents it reads. Every
    field reaches a key or the manifest, which is why they travel together: a
    field added here is a field the plan has to account for.

    `reference_content` is what the `reference:` sources hold, by kind and then
    by key: the context every call reading `reference` is shown whole (R3.18).
    `reference_documents` pins each by snapshot, as `documents` pins the
    audited ones, so a replay shows those calls the same context (R4.16).
    """

    pipeline: PipelineConfig
    pipeline_hash: str
    schemas: Mapping[str, OutputSchema | None]
    prompts: Mapping[str, str]
    documents: Mapping[str, str]
    document_text: Mapping[str, str]
    media_types: Mapping[str, str] | None = None
    document_content: Mapping[str, Mapping[str, str]] | None = None
    document_parts: Mapping[str, Mapping[str, Sequence[tuple[str, ImagePart]]]] | None = None
    reference_content: Mapping[str, Mapping[str, str]] | None = None
    reference_documents: Mapping[str, str] | None = None
    converters: Sequence[PinnedConverter] | None = None
    source_configs: Mapping[str, SourceConfig] | None = None


@dataclass(frozen=True)
class RunRecording:
    """Where a run is recorded, and how much of it: nothing here changes an output (R10.4).

    With a `tracker`, the run is also recorded to `experiment`: one MLflow run
    named after the run id, one trace per (step, document), and the counts and
    the manifest once the steps are done (R11.1). `versions` registers the
    pipeline version it produced (spec 013), and `prompt_registry` links the
    prompts its steps rendered (spec 014). The default records nothing.
    """

    tracker: Tracker | None = None
    experiment: str | None = None
    environ: Mapping[str, str] | None = None
    label: str = ""
    capture: str = "full"
    versions: VersionRegistry | None = None
    version_experiment: str = ""
    prompt_registry: PromptRegistry | None = None
    prompt_prefix: str = ""


# A run nothing records: no tracker, no registry. Frozen, so one serves every call.
NOT_RECORDED = RunRecording()


def execute(
    inputs: RunInputs,
    *,
    workspace: Path,
    model: ModelClient,
    cache: ArtifactStore,
    run_id: str,
    started_at: datetime,
    dossier_version: str,
    models: Mapping[str, ModelClient] | None = None,
    concurrency: int = 1,
    recording: RunRecording = NOT_RECORDED,
    tried: Sequence[str] | None = None,
) -> RunReport:
    """Resolve the pipeline, freeze it, then run it.

    Raises `ValueError` if resolution fails, having written nothing and called
    nothing. Returns a report if it succeeded, whatever individual documents did.

    What is run is `inputs`, and where it is recorded is `recording`: the one
    can change an output and the other may not (R0.5, R10.4), so the two are
    never one argument list.

    `model` asks every step that names no model of its own; `models` holds a
    client for each model a step does name, by its identifier (R3.14). A step
    whose model has no client stops the run before anything is written.

    `concurrency` is how many of a step's documents are asked about at once
    (R9.19). Steps still run one after another, and every result is put back in
    document order, so nothing this returns or writes depends on it.

    `tried` is a try's: the documents `dossier run --doc` names. Each step is
    asked only about those (R4.18); `None` is a full run.

    Recording starts only after resolution, so a run that resolution refused
    records nothing either. Tracking observes; nothing it holds is read back
    into this run (R0.10).
    """
    pipeline, pipeline_hash = inputs.pipeline, inputs.pipeline_hash
    schemas, prompts = inputs.schemas, inputs.prompts
    documents, media_types = inputs.documents, inputs.media_types
    document_text, document_content = inputs.document_text, inputs.document_content
    document_parts = inputs.document_parts
    reference_content, reference_documents = (
        inputs.reference_content,
        inputs.reference_documents,
    )
    converters, source_configs = inputs.converters, inputs.source_configs
    tracker, experiment, environ = recording.tracker, recording.experiment, recording.environ
    label, capture = recording.label, recording.capture
    versions, version_experiment = recording.versions, recording.version_experiment
    prompt_registry, prompt_prefix = recording.prompt_registry, recording.prompt_prefix

    if tracker is not None and not experiment:
        raise ValueError("a tracker records to an experiment, and none was named")
    # What each kind holds, for the steps that name one (R3.11). A caller that
    # passes only `document_text` is passing the markdown kind, which is what
    # every input meant before a kind could be written down.
    by_kind: Mapping[str, Mapping[str, str]] = (
        {DEFAULT_INPUT_KIND: document_text} if document_content is None else document_content
    )
    # The parts of each kind that has any, for the per_part steps that fan out
    # over them (R3.12). Absent for every kind whose artifact is one blob.
    by_part: Mapping[str, Mapping[str, Sequence[tuple[str, ImagePart]]]] = document_parts or {}
    by_reference: Mapping[str, Mapping[str, str]] = reference_content or {}
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
        source_configs=source_configs,
        reference=reference_documents,
    )
    # Which client asks each step: its own model's, or the pipeline's (R3.14).
    # Decided before anything is written, so a step whose model has no client
    # is refused like any other resolution error.
    clients = _clients(plan, default=model, models=models or {})

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
            name=run_name(
                kind="run",
                values={
                    "pipeline": pipeline.name,
                    "started": f"{started_at:%Y%m%dT%H%M%SZ}",
                    "run_id": run_id,
                    "model": plan.model,
                    "pipeline_hash": plan.pipeline_hash,
                    "label": label,
                },
                environ=environ or {},
            ),
            tags=tracking_tags(
                kind="run", pipeline=pipeline.name, label=label, environ=environ or {}
            ),
        )
        tracker.log_params(
            {
                "pipeline": pipeline.name,
                "model": plan.model,
                # Which dossier wrote this record (R11.19). The value R4.9
                # already puts in every manifest: a record is a second place
                # to read it, never a second way of arriving at it.
                "dossier_version": dossier_version,
                # How many documents it asked about at once (R11.21), so two
                # runs' durations are compared knowing it. The record's alone:
                # it reaches no key, manifest or provenance record (R9.19).
                "concurrency": str(concurrency),
                # The version of everything this run is about to use, off the
                # plan it has just resolved: the same function over the same
                # data that the eval scoring this run reads off its manifest
                # (R11.18). `pipeline_hash` is among them. Recorded here
                # and not only there, because "which prompt moved" is the
                # question MLflow's run comparison exists for, and two runs of
                # one pipeline could not answer it.
                **version_params(plan),
            }
        )
        # The pipeline version this run is about to build: registered, then
        # linked as one of this run's outputs (R13.1, R13.2). The registry
        # is best-effort and answers `None` when the server cannot hold a
        # logged model, which costs the record and never the run (R13.5).
        built: str | None = None
        if versions is not None:
            registered = versions.register(
                record=version_record(plan), experiment=version_experiment
            )
            if registered is not None:
                tracker.produced_version(registered.version_id)
                built = registered.version_id

        # The prompt version each step rendered, found by the hash the plan
        # already holds rather than by recency: a prompt edited and republished
        # since this text was written would otherwise attach its newest words
        # to a run that never saw them (R14.7 row 1). A step whose prompt was
        # never published finds nothing and links nothing -- a run must not
        # fail, or even differ, because someone has not run `prompts publish`
        # (R10.4).
        #
        # The version this run built is made of exactly these prompts -- its
        # hash is taken over theirs (R13.1) -- so each one found is linked to
        # it as well, from the same lookup (R14.12). This command, and not an
        # eval, because it is the one that made the version (R13.2).
        if prompt_registry is not None:
            link_published(
                tracker,
                prompt_registry,
                [
                    (
                        prompt_name(pipeline.name, step.id, prefix=prompt_prefix),
                        step.prompt_hash,
                    )
                    for step in plan.steps
                ],
                version_id=built,
            )

    # A run that stops -- an unreachable model, an interrupt -- is recorded as
    # failed rather than left looking as if it were still running (R11.23).
    with failed_if_stopped(tracker):
        for step in plan.steps:
            over = asked_about(_units(declared[step.id].mode, keys), tried=tried)
            output = schemas.get(step.id)
            results: list[DocumentResult] = []
            every_part: list[DocumentResult] = []

            # `step` and `output` bound now: `one` runs on other threads, but
            # always before this loop moves on, and binding says so.
            def one(
                key: str, *, step: ResolvedStep = step, output: OutputSchema | None = output
            ) -> tuple[DocumentResult, list[DocumentResult]] | None:
                # A document an earlier step produced nothing for is skipped,
                # not run with an empty input: that would ask a model about a
                # document nobody read and cache the answer under a key whose
                # input hash is the hash of `""` -- invisible in the provenance
                # record, and served again next run (R6.13, R5.5). It already
                # failed once, at the step that could not produce its output.
                if not _reads_a_set(declared[step.id].mode) and _missing_input(
                    declared=declared[step.id],
                    resolved=step,
                    document=key,
                    produced=produced,
                ):
                    return None
                # Nor for a document the source gave nothing of the kinds this
                # step reads: a picture, to a step reading text. Asked anyway,
                # every picture had the key of `""`, and the second was served
                # the first one's answer (R6.21).
                if not _reads_a_set(declared[step.id].mode) and _reads_nothing(
                    targets=_targets(declared[step.id], step),
                    document=key,
                    holds=lambda kind: _held(kind, by_kind=by_kind, by_part=by_part),
                ):
                    return None

                # One trace per (step, document): the unit of a cache key, so one
                # trace is one key computed or served (spec 011). Opened before
                # the work, so what happens inside it is recorded inside it.
                # Written as each part finishes, not when the run ends: a run
                # killed in `verify` still leaves `describe/` complete for the
                # person who opens it (R0.11 row 3). A failed part leaves
                # nothing, as a failed document does (R0.13 row 3).
                parts_done: list[DocumentResult] = []
                # Each answered part's name and the file `runs/` holds for it,
                # which is what a `per_part` document's trace shows (R15.6).
                pages: list[tuple[str, str]] = []
                if tracker is not None:
                    tracker.start_trace(
                        name=f"{step.id} · {key}",
                        tags={"dossier.step": step.id, "dossier.document": key},
                        # What a reviewer reads first: the document and what the
                        # step was handed about it (R15.1). Built where a failure
                        # is caught, so it costs the record and never the run
                        # (R10.25).
                        inputs=record_content(
                            lambda: trace_request(
                                key,
                                _input_values(
                                    declared=declared[step.id],
                                    resolved=step,
                                    document=key,
                                    documents=_members(declared[step.id].mode, key, keys),
                                    aggregate=_reads_a_set(declared[step.id].mode),
                                    by_kind=by_kind,
                                    reference=by_reference,
                                    produced=produced,
                                ),
                                capture=capture,
                            ),
                            otherwise=lambda why: {"document": key, "error": why},
                        ),
                    )
                # A per_part step runs once per part of its input, keyed and
                # retried per part (R3.12). `[None]` is every other step: one
                # call, no part, and a key composed exactly as it always was.
                for part in _parts_for(
                    declared=declared[step.id], resolved=step, document=key, by_part=by_part
                ):
                    result, stage_key = _run_one(
                        step=step,
                        declared=declared[step.id],
                        document=key,
                        documents=_members(declared[step.id].mode, key, keys),
                        document_text=document_text,
                        by_kind=by_kind,
                        reference=by_reference,
                        produced=produced,
                        part=part,
                        schema=None if output is None else output.schema,
                        lists=() if output is None else output.lists,
                        enums={} if output is None else output.enums,
                        prompt=prompts[step.id],
                        model=clients[step.id],
                        cache=cache,
                        run_id=run_id,
                        dossier_version=dossier_version,
                        tracker=tracker,
                        capture=capture,
                    )
                    if not result.failed:
                        _publish(
                            run_dir=manifest.parent,
                            step=step.id,
                            document=key,
                            structured=output is not None,
                            payload=_as_text(result).encode(),
                            record=cache.record(stage_key),
                            part=None if part is None else part[0],
                        )
                        if part is not None:
                            pages.append((part[0], _as_text(result)))
                    parts_done.append(_on_part(result, part))

                if not parts_done:
                    # A per_part step whose document has no parts. The document
                    # is simply absent from this step, the same shape as one an
                    # earlier step produced nothing for (R6.13) -- and better
                    # than one call with no picture, which would ask the model
                    # to describe nothing and cache the answer.
                    if tracker is not None:
                        tracker.end_trace(status="OK", error=None)
                    return None

                result = (
                    parts_done[0]
                    if len(parts_done) == 1 and declared[step.id].mode != "per_part"
                    else _joined_parts(parts_done, document=key)
                )
                if tracker is not None:
                    tracker.end_trace(
                        status="ERROR" if result.failed else "OK",
                        error=result.error,
                        # And the answer beside it, as `runs/` holds it (R15.1):
                        # for a `per_part` document, one file per page, never the
                        # joined text a later step reads, which is not JSON (R15.6).
                        outputs=record_content(
                            lambda: (
                                trace_pages(
                                    pages, structured=output is not None, capture=capture
                                )
                                if declared[step.id].mode == "per_part" and not result.failed
                                else trace_response(
                                    None if result.failed else _as_text(result),
                                    structured=output is not None,
                                    error=result.error if result.failed else None,
                                    capture=capture,
                                )
                            ),
                            otherwise=lambda why: {"error": why},
                        ),
                        # What the run doubts about it, for the review queue
                        # (R15.2). Checks pair with records one to one.
                        tags=record_content(
                            lambda: review_tags(
                                failed=result.failed,
                                verdicts=[
                                    (record.field, check.verdict)
                                    for record, check in zip(
                                        result.records, result.checks, strict=True
                                    )
                                ],
                            ),
                            otherwise=unbuilt_tags,
                        ),
                    )
                return result, parts_done if declared[step.id].mode == "per_part" else []

            # At most `concurrency` documents at once, collected in document
            # order whatever order they finish in: the step lines, `runs/` and
            # every record are what one at a time writes (R9.19).
            for done in _in_order(over, one, concurrency=concurrency):
                if done is None:
                    continue
                result, parts = done
                every_part.extend(parts)
                results.append(result)
            steps.append(
                StepReport(
                    step=step.id,
                    results=tuple(results),
                    parts=tuple(every_part),
                    unit="group" if declared[step.id].mode == "per_group" else "document",
                )
            )
            produced[step.id] = {
                result.document: _as_text(result) for result in results if not result.failed
            }

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
                # What the run spent, from the same sums its step lines print
                # (R5.12, R11.20); neither, when a provider did not say.
                **token_metrics(
                    total(done.tokens for done in report.steps if done.tokens is not None)
                ),
            }
        )
        tracker.log_artifact(manifest.name, manifest.read_bytes())
        # What the terminal is about to print, in the record's Description
        # (R11.17). Composed from the same function the CLI prints with, so
        # the two cannot say different things about one run.
        tracker.describe(
            run_description(
                run_id=run_id,
                pipeline=pipeline.name,
                model=plan.model,
                pipeline_hash=plan.pipeline_hash,
                lines=[
                    step_line(
                        step=done.step,
                        documents=len(done.results),
                        cached=len(done.served_from_cache),
                        failed=len(done.failed),
                        described=done.described,
                        findings=len(done.findings),
                        tokens=done.tokens,
                        unit=done.unit,
                    )
                    for done in report.steps
                ],
            )
        )
        tracker.end_run(status="FAILED" if report.failed else "FINISHED")
    return report


def _clients(
    plan: ResolvedPlan, *, default: ModelClient, models: Mapping[str, ModelClient]
) -> dict[str, ModelClient]:
    """The client each step is asked with, by step id (R3.14).

    A step that names no model of its own is asked with `default`, the
    pipeline's. One that does is asked with the client for that model, and a
    model with none is refused here -- before a manifest is written or a model
    asked -- rather than at the step's first cache miss, half a run later.
    """
    clients: dict[str, ModelClient] = {}
    for step in plan.steps:
        if step.model is None:
            clients[step.id] = default
        elif step.model in models:
            clients[step.id] = models[step.model]
        else:
            raise ValueError(
                f"step {step.id!r} is asked with {step.model}, and no client was given for it"
            )
    return clients


def _in_order[T, R](items: Sequence[T], work: Callable[[T], R], *, concurrency: int) -> list[R]:
    """`work` over `items`, at most `concurrency` at once, in `items`' order (R9.19).

    One at a time is a plain loop in this thread, the run before R9.19 exactly.
    Otherwise items start in their order, so every item before one that fails
    has been started; the results are read back in that order, so the error
    raised is the first failing item's -- the one a loop would have stopped at.
    Once anything fails, or the caller is interrupted, an item not yet started is
    not started. The ones in flight are waited for: a call cannot be taken back,
    and an answer it paid for is cached as it completes.
    """
    if concurrency == 1 or len(items) < 2:
        return [work(item) for item in items]
    stopped = threading.Event()

    def guarded(item: T) -> R | None:
        # `None` is never read: an item only goes unstarted after an earlier
        # one failed, and reading that one's result raises first.
        if stopped.is_set():
            return None
        try:
            return work(item)
        except BaseException:
            stopped.set()
            raise

    with ThreadPoolExecutor(max_workers=min(concurrency, len(items))) as pool:
        started = [pool.submit(guarded, item) for item in items]
        try:
            return [future.result() for future in started]
        except BaseException:
            stopped.set()
            raise


def _as_text(result: DocumentResult) -> str:
    """One step's output: the artifact it is cached as, and the text below it reads.

    Serialised from the validated records rather than from the model's raw reply,
    so a cache hit and a fresh run produce the same bytes even where the model
    answered with different whitespace (R5.5).

    A step with no schema has no records to serialise, and its prose is the
    artifact as written -- there is nothing to normalise it against, and nothing
    here to indent (R0.14 row 5).

    Indented, one key per line, ending in a newline (R0.14). This is the file a
    reviewer opens when a score disagrees with an answer, and it was the one file
    in the workspace written on a single line. Keys keep the order `StageOutput`
    declares them in rather than being sorted: `document` before `fields` is how
    the record reads, and sorting would be a second decision taken for the sake
    of a first.
    """
    if result.text is not None:
        return result.text
    return (
        StageOutput(document=result.document, fields=list(result.records)).model_dump_json(
            indent=2
        )
        + "\n"
    )


def _run_one(
    *,
    step: ResolvedStep,
    declared: StepConfig,
    document: str,
    documents: Sequence[str],
    document_text: Mapping[str, str],
    by_kind: Mapping[str, Mapping[str, str]],
    reference: Mapping[str, Mapping[str, str]],
    produced: Mapping[str, Mapping[str, str]],
    part: tuple[str, ImagePart] | None = None,
    schema: dict | None,
    prompt: str,
    model: ModelClient,
    cache: ArtifactStore,
    run_id: str,
    dossier_version: str,
    tracker: Tracker | None = None,
    capture: str = "full",
    lists: Collection[str] = (),
    enums: Mapping[str, Sequence[str]] | None = None,
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
        aggregate=_reads_a_set(declared.mode),
        by_kind=by_kind,
        reference=reference,
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
        ]
        # The part is an input like any other, hashed by content. That is what
        # makes each page its own key without spec 005 needing a rule about
        # parts: page two differs from page one because its bytes do (R3.12).
        + (
            []
            if part is None
            else [
                ArtifactInput(
                    role="part",
                    path=f"part/{document}/{part[0]}",
                    hash=content_hash(part[1].data),
                )
            ]
        )
        + _group_input(declared.mode, document),
    )
    key = cache_key(key_inputs)

    # A stage was shown pictures of this document exactly when it was handed
    # one of its parts (R3.12). Local and certain, rather than inferred later
    # from the document being absent from the text map -- which is also true of
    # a document the stage never read at all (R6.15).
    shown_as_pictures = () if part is None else (document,)

    # What a citation may name: for a group's call, its members and no others. A
    # group's answer quoting another contract would be a quote the call was
    # never shown, and it would look checkable (R6.22, R6.3). Every other mode
    # is checked against the text it always was.
    read = _citable(
        mode=declared.mode,
        document=document,
        documents=documents,
        targets=_targets(declared, step),
        document_text=document_text,
        reference=reference.get(DEFAULT_INPUT_KIND, {}),
    )

    hit = cache.get(key, require_record=True)
    if hit is not None:
        served = _from_cache(
            document=document,
            payload=hit,
            document_text=read,
            shown_as_pictures=shown_as_pictures,
            structured=schema is not None,
            enums=enums,
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
        input_documents=read,
        parts=() if part is None else (part[1],),
        shown_as_pictures=shown_as_pictures,
        tracker=tracker,
        capture=capture,
        lists=lists,
        enums=enums,
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
                tokens=result.tokens,
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
    part: str | None = None,
) -> None:
    """Put one artifact and its record under `runs/<run_id>/` (R0.11).

    The bytes are the cache entry's, not a re-rendering: a person opening
    `extract/INC-4821.json` reads exactly what the next step was shown. The
    record is serialised as the cache serialises it, so the two siblings match
    byte for byte (R0.3). Nothing here is ever read back -- `runs/` is a copy for
    a person, and the cache stays the only authority (row 6).
    """
    name = output_path(step, document, structured=structured, part=part)
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
    shown_as_pictures: Collection[str] = (),
    structured: bool = True,
    enums: Mapping[str, Sequence[str]] | None = None,
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
    records = tuple(
        with_derived_page(record, input_documents=document_text) for record in output.fields
    )
    checks = tuple(
        check_field(
            record,
            input_documents=document_text,
            shown_as_pictures=shown_as_pictures,
            # An answer written before R6.26 is held to it on this read, as
            # every check is re-derived rather than stored (R5.5).
            enums=enums,
        )
        for record in records
    )
    return DocumentResult(
        document=document,
        records=records,
        checks=checks,
        attempts=0,
        # The stored bytes travel on rather than being re-derived from the
        # records. They are the same bytes for every document that shares this
        # key, and two documents with identical content do share one -- so
        # re-serialising under *this* document's name would hand the next step
        # something the cache never held, and change its key (R5.5, R5.7 row 4).
        text=payload.decode(),
    )


def _group_input(mode: str, unit: str) -> list[ArtifactInput]:
    """The group a `per_group` call is about, as an input to its key (R5.14 row 5).

    A group of one file renders byte for byte as that file's `per_file` call,
    so without its name the two shared a key, and the group was served the
    answer written about its file -- `extract/GLOBEX-2023.json` holding
    `"document": "GLOBEX-2023/master.md"`, which is R5.10 row 5's failure. The
    cached bytes travel as they are (R5.5), so the name cannot be put right when
    the answer is served; it is kept out of the entry instead. Empty for every
    other mode, whose keys are composed exactly as they always were.
    """
    if mode != "per_group":
        return []
    return [ArtifactInput(role="group", path=f"group/{unit}", hash=content_hash(unit.encode()))]


def _units(mode: str, keys: Sequence[str]) -> list[str]:
    """What a step is asked about once each: a document, a group, or the corpus.

    `per_group` runs once per group -- the documents whose keys share a first
    segment, such as a contract and its amendments (R3.15). Sorted, so a run's
    step lines and records come out in the same order on every machine (R0.4).
    """
    if mode == "aggregate":
        return [AGGREGATE_KEY]
    if mode == "per_group":
        return sorted({group_of(key) for key in keys})
    return list(keys)


def _members(mode: str, unit: str, keys: Sequence[str]) -> list[str]:
    """The documents one call of this step is shown, for the unit it is about.

    A group's call holds what an aggregate call holds, limited to the group
    (R3.15). Every other mode is handed every key, as it always was: `per_file`
    reads its one document out of them, and `aggregate` reads them all.
    """
    if mode == "per_group":
        return [key for key in keys if group_of(key) == unit]
    return list(keys)


def _reads_a_set(mode: str) -> bool:
    """Whether one call of this step reads several documents, each wrapped by key.

    An `aggregate` call reads every document, and a `per_group` call its group's
    (R3.15). Neither is skipped for one member missing an input: a set with a
    member absent is still a set, and skipping it would throw away the members
    that did work (R6.13 row 4).
    """
    return mode in ("aggregate", "per_group")


def _citable(
    *,
    mode: str,
    document: str,
    documents: Sequence[str],
    targets: Sequence[str],
    document_text: Mapping[str, str],
    reference: Mapping[str, str],
) -> dict[str, str]:
    """The documents a field of this call may cite, with their text (R6.23).

    What the call was shown: its own document for `per_file` and `per_part`,
    its members for `per_group` (R6.22), every audited document for
    `aggregate`, and every reference document when the step reads
    `reference` (R3.18). Handed the whole corpus instead, a check grounded an
    answer about INC-4821 that quoted INC-4822, a document its call never
    read: the citation R6.3 calls worse than none, because it looks
    checkable. `execute` and `replay` both ask this, so a replay grades an
    answer as the run did.
    """
    shown = documents if _reads_a_set(mode) else [document]
    citable = {key: document_text[key] for key in shown if key in document_text}
    if any(split_kind(target)[0] == REFERENCE for target in targets):
        citable.update(reference)
    return citable


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
        if split_kind(target)[0] not in SOURCE_KEYWORDS
    )


def _reads_nothing(
    *, targets: Sequence[str], document: str, holds: Callable[[str], Collection[str]]
) -> bool:
    """Whether `document` holds nothing of any kind this step reads from `documents` (R6.21).

    Only `documents`: those are what the step runs over, one call each. A step
    reading no `documents` at all -- only earlier steps' output -- is R6.13's
    to decide. `execute` and `replay` both ask this, each saying what it holds,
    because a replay that asked for a document the run skipped would look for
    an entry that was never written (R4.7).
    """
    kinds = [
        kind or DEFAULT_INPUT_KIND
        for name, kind in (split_kind(target) for target in targets)
        if name == DOCUMENTS
    ]
    return bool(kinds) and not any(document in holds(kind) for kind in kinds)


def _held(
    kind: str,
    *,
    by_kind: Mapping[str, Mapping[str, str]],
    by_part: Mapping[str, Mapping[str, Sequence[tuple[str, ImagePart]]]],
) -> set[str]:
    """The documents that hold `kind`: as text, or as parts."""
    return set(by_kind.get(kind, {})) | set(by_part.get(kind, {}))


def _parts_for(
    *,
    declared: StepConfig,
    resolved: ResolvedStep,
    document: str,
    by_part: Mapping[str, Mapping[str, Sequence[tuple[str, ImagePart]]]],
) -> list[tuple[str, ImagePart] | None]:
    """The parts one call of this step runs over, or `[None]` for one call.

    `[None]` rather than `[]` for every step that is not `per_part`: the loop
    above runs once either way, and an empty list would silently skip the step
    instead of running it once with no part.

    A `per_part` step whose document has no parts yields nothing at all, and the
    document is simply absent from the step -- the same shape as a document an
    earlier step produced nothing for (R6.13).
    """
    if declared.mode != "per_part":
        return [None]

    for name in declared.inputs:
        _, kind = split_kind(name)
        if kind is None:
            continue
        found = by_part.get(kind, {}).get(document)
        if found:
            return list(found)
    return []


def _on_part(result: DocumentResult, part: tuple[str, ImagePart] | None) -> DocumentResult:
    """A part's result, each of its records labelled with the part it came from (R7.48).

    Labelled here, where the part is known, because the join below is where a
    document's pages become one list of records, and the page each came from
    would be lost in it.
    """
    if part is None:
        return result
    return replace(result, parts=(part[0],) * len(result.records))


def _joined_parts(results: Sequence[DocumentResult], *, document: str) -> DocumentResult:
    """One document's parts as the single result a later step reads (R3.12).

    Each part wrapped in a tag naming it, in part order -- the shape `aggregate`
    already uses for documents (spec 003, "Prompt files"), and for the same
    reason: a model asked to attribute a finding needs to know which page it
    read it on.

    A part that failed is left out rather than represented by an empty tag, and
    its failure is still carried: a document whose pages half worked is a
    partial answer and has to read as one.

    The records and checks travel with it, concatenated in part order. They
    were dropped here once, which made every grounding finding a `per_part`
    step produced invisible to the report -- the step ran, the pages were
    checked, and nothing reading the result could tell. A document's fields
    are its pages' fields, whatever the fan-out did on the way (R6.15).
    """
    kept = [result for result in results if not result.failed]
    failed = [result for result in results if result.failed]
    body = "\n".join(f'<part name="{part.document}">{_as_text(part)}</part>' for part in kept)
    return DocumentResult(
        document=document,
        records=tuple(record for part in kept for record in part.records),
        checks=tuple(check for part in kept for check in part.checks),
        parts=tuple(name for part in kept for name in part.parts),
        attempts=sum(result.attempts for result in results),
        tokens=total(result.tokens for result in results),
        text=body,
        error="; ".join(result.error or "" for result in failed) or None,
    )


def _input_values(
    *,
    declared: StepConfig,
    resolved: ResolvedStep,
    document: str,
    documents: Sequence[str],
    aggregate: bool,
    by_kind: Mapping[str, Mapping[str, str]],
    reference: Mapping[str, Mapping[str, str]],
    produced: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """What each declared input holds, for this call.

    Keyed by the name the *prompt* uses, which is the name as declared -- sugar
    included, because that is the form R3.6 checked at load time. The resolved
    ids say where the content comes from.

    In a `per_file` step each value is one document's text. In an `aggregate`
    step it is every document, each wrapped in a tag naming its key (spec 003).
    `reference` is every reference document in every mode (R3.18).
    """
    values: dict[str, str] = {}
    for name, target in zip(declared.inputs, _targets(declared, resolved), strict=True):
        if split_kind(target)[0] == REFERENCE:
            # Context, not a document this call is about. The call about
            # INC-4821 and the call about INC-4822 are checked against the same
            # procedures, so both are shown all of them, whatever the mode.
            # Filled from the audited documents' map, as it once was, it held
            # the incident a second time and never a procedure (R3.18).
            _, kind = split_kind(name)
            held = reference.get(kind or DEFAULT_INPUT_KIND, {})
            values[name] = _joined(held, list(held))
            continue
        # A resolved target keeps the kind it was declared with -- expansion
        # only rewrites `previous`, and `documents@page_images` was already
        # concrete. So the kind comes off before asking what this names.
        if split_kind(target)[0] in SOURCE_KEYWORDS:
            # The kind the input asked for, which is `markdown` when it asked
            # for none (R3.11). Keeping only the markdown map here was what made
            # `page_images` an artifact no step could reach: the words existed
            # in the pipeline and nothing acted on them.
            _, kind = split_kind(name)
            source = by_kind.get(kind or DEFAULT_INPUT_KIND, {})
        else:
            source = produced.get(target, {})
        values[name] = _one_value(
            source, document=document, documents=documents, aggregate=aggregate
        )
    return values


def _one_value(
    source: Mapping[str, str],
    *,
    document: str,
    documents: Sequence[str],
    aggregate: bool,
) -> str:
    """What one input holds for one call (R3.13).

    The single place the mode decides what a placeholder gets. `execute` and
    `replay` both come here, which is the point: a replay recomposes its keys
    from these values (R4.14), so a rendering the two disagreed about would
    build a key no run had ever written and make every run irreproducible. That
    decision used to be written out twice, in this function's caller and in
    `_replayed_input`, and the two agreeing was a thing someone had to remember.
    """
    if aggregate:
        # Under the groups as well as the members: an earlier `per_group`
        # step's answers are filed there, and nowhere else (R3.16).
        return _joined(source, filed_under(documents))
    # Wrapped exactly as the aggregate branch wraps, because the reason is the
    # same one: a stage asked to carry a document key in `source.document` has
    # to be shown that key. A stage that has to guess reads it off the note's
    # own heading, answers `PLAY-1001` for a document keyed `PLAY-1001.md`, and
    # is `invalid` under R6.3 with every value beside it right (R3.13).
    #
    # Absent stays absent rather than becoming an empty wrapper: a document the
    # step produced nothing for is not a document that was read and said
    # nothing, and `_joined` draws the same line.
    content = source.get(document)
    return "" if content is None else _wrapped(document, content)


def _wrapped(key: str, content: str) -> str:
    """One document's content under a tag naming the key it came from (R3.13).

    The one wrapper in the system. Every branch of `_one_value` calls it, so a
    `per_file` step and an `aggregate` step cannot describe the same document
    two different ways -- which is what the asymmetry this replaced amounted to.
    """
    return f'<document key="{key}">{content}</document>'


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
    return "\n".join(_wrapped(key, source[key]) for key in sorted(documents) if key in source)


def group_evidence(texts: Mapping[str, str]) -> dict[str, str]:
    """Each group's text, as its `per_group` call was shown it (R7.33).

    Every member wrapped under its own key, in key order -- `_joined`, the same
    rendering the stage's call used -- so a judge asked about a group's answer
    weighs the evidence the answer was made from. A claim may stand on two
    members, and a judge shown only the one it cites would weigh half of it.
    """
    members: dict[str, list[str]] = {}
    for key in texts:
        members.setdefault(group_of(key), []).append(key)
    return {group: _joined(texts, keys) for group, keys in sorted(members.items())}


def reference_context(reference: Mapping[str, str]) -> str:
    """Every reference document, each under its own key in key order (R3.18).

    What a call reading `reference` was shown beside its own document,
    rendered as `_input_values` rendered it, so a judge asked about the
    answer is shown the context the stage was (R7.34).
    """
    return _joined(reference, list(reference))


def judge_evidence(
    texts: Mapping[str, str], *, mode: str, reference: Mapping[str, str]
) -> dict[str, str]:
    """What a judge is shown for each answer: the evidence its call read.

    A document's text, as R7.17 always showed it; a group's members, each
    under its own key (R7.33). A step that read `reference` answered from
    that and the procedures together, so its judge is shown both: the
    document under its own key, or the group, and then every reference
    document (R7.34). A claim resting on the 30 minutes OPS-114 allows is
    otherwise judged unsupported, a mistake no calibration measured.
    """
    evidence = group_evidence(texts) if mode == "per_group" else dict(texts)
    if not reference:
        return evidence
    if mode != "per_group":
        evidence = {key: _wrapped(key, text) for key, text in evidence.items()}
    context = reference_context(reference)
    return {unit: f"{text}\n{context}" for unit, text in evidence.items()}


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
    source_configs: Mapping[str, SourceConfig] | None = None,
    reference: Mapping[str, str] | None = None,
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
    validate_modes(pipeline)
    if source_configs is not None:
        # Refused here, from the configuration alone, before a byte is fetched
        # or a model is reached (R4.13). Skipped when the caller did not supply
        # the sources -- a replay resolves a pipeline whose sources.yaml may no
        # longer exist, and refusing it on that would break R4.7.
        check_kinds(
            steps=pipeline.steps,
            sources=[
                source_configs[name] for name in pipeline.sources if name in source_configs
            ],
            reference=[
                source_configs[name] for name in pipeline.reference if name in source_configs
            ],
        )
    plan = resolve(
        pipeline=pipeline,
        pipeline_hash=pipeline_hash,
        documents=documents,
        media_types=media_types,
        prompt_hashes=prompt_hashes,
        schema_hashes=schema_hashes,
        generated_schema_hashes=generated_schema_hashes,
        converters=converters,
        reference=reference,
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
    # The context the run read as well as what it audited: a call that read
    # `reference` is recomposed from these texts too (R4.16).
    pinned = [*manifest.plan.documents, *manifest.plan.reference]
    missing = [
        f"  {document.key}: no snapshot for {document.snapshot[:12]}..."
        for document in pinned
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
    for document in pinned:
        converter = claimed.get((document.media_type, MARKDOWN))
        if converter is None:
            # Not an error. The manifest records the converters the run used,
            # so no markdown converter for this media type means the run never
            # made text of it -- a source declaring `convert: [page_images]`,
            # whose evidence is its pages (R6.15). There is no text to
            # reproduce, and demanding some would make a picture-only run
            # irreproducible for want of an artifact it never had.
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


def replayed_parts(
    manifest: Manifest, *, store: SnapshotReader, cache: ArtifactStore
) -> dict[str, dict[str, list[tuple[str, ImagePart]]]]:
    """The parts a past run fanned a `per_part` step out over, by kind (R4.14).

    Re-derived rather than recorded. The manifest already pins each snapshot and
    each converter the run used, which is what `replayed_inputs` recomposes the
    text from; a container is fetched through the same composition and unpacked,
    so a replay still reads nothing but entries the original run wrote (R4.7).

    Silent about what it cannot find, deliberately. Which kinds a run actually
    needs is a question about its steps, and `_replay_one` is where that is
    known -- a document whose parts are gone stops the replay there, naming the
    part rather than the kind, which is what a person can act on.
    """
    by_kind: dict[str, dict[str, list[tuple[str, ImagePart]]]] = {}
    for converter in manifest.plan.converters:
        for document in manifest.plan.documents:
            if document.media_type != converter.media_type:
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
                continue
            try:
                unpacked = unpack_parts(stored)
            except ValueError:
                # Not a container. A `markdown` artifact is bytes of text and
                # reaches a step as a substitution, never as a part (R8.11).
                continue
            by_kind.setdefault(converter.kind, {})[document.key] = [
                (part_name(position, PART_SUFFIX), ImagePart(media_type=PART_TYPE, data=part))
                for position, part in enumerate(unpacked, 1)
            ]
    return by_kind


def replay(
    *,
    manifest: Manifest,
    document_text: Mapping[str, str],
    cache: ArtifactStore,
    document_parts: Mapping[str, Mapping[str, Sequence[tuple[str, ImagePart]]]] | None = None,
    destination: Path | None = None,
    enums: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
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

    `enums`, by step, is the one thing a caller may hand in from a declaration:
    the values each enum field allows, which the field checks read (R6.26). It
    decides a verdict, never a key or an answer, so nothing reproduced depends
    on it -- and `dossier eval`, which scores this, already reads the
    declaration for each field's kind.

    With a `destination`, what was reproduced is written there, named as a run
    names its outputs (R0.11) -- and only once every key has resolved. A
    missing entry raises before anything is written, so a failed replay leaves
    no directory at all: three of four documents beside a manifest pinning four
    would read as a complete run to anyone who did not see the error (R0.12).
    """
    plan = manifest.plan
    keys = [document.key for document in plan.documents]
    # The context the run's calls were shown, at the snapshots it pinned, and
    # never what is held now (R4.16).
    reference = {
        pinned.key: document_text[pinned.key]
        for pinned in plan.reference
        if pinned.key in document_text
    }
    steps: list[StepReport] = []
    produced: dict[str, dict[str, str]] = {}
    reproduced: list[tuple[str, str, bool, bytes, dict | None, str | None]] = []

    by_part = {} if document_parts is None else document_parts

    for step in plan.steps:
        # The units `execute` ran over, recomposed from the manifest's keys alone:
        # a group is read off its members' keys, so a document synced since the
        # run is in no group here (R4.15).
        over = _units(step.mode, keys)
        results: list[DocumentResult] = []
        every_part: list[DocumentResult] = []
        for document in over:
            # The same fan-out `execute` ran, so the keys recomposed here are
            # the keys it wrote. A `per_part` step whose parts are gone raises
            # inside `_replay_one`, naming the part (R4.14).
            # What `execute` skipped, skipped here, or the replay would look
            # for an entry the run never wrote (R6.21, R4.7). Replay holds
            # text as `document_text`, which is only ever the markdown kind.
            if not _reads_a_set(step.mode) and _reads_nothing(
                targets=step.inputs,
                document=document,
                holds=lambda kind: _held(
                    kind, by_kind={DEFAULT_INPUT_KIND: document_text}, by_part=by_part
                ),
            ):
                continue
            parts = _replayed_parts_for(step=step, document=document, by_part=by_part)
            served: list[DocumentResult] = []
            for part in parts:
                result, key = _replay_one(
                    step=step,
                    document=document,
                    documents=_members(step.mode, document, keys),
                    # The model this step was asked with, as the run keyed it:
                    # its own where it named one (R3.14, R4.7).
                    model=plan.model_of(step),
                    document_text=document_text,
                    reference=reference,
                    produced=produced,
                    cache=cache,
                    part=part,
                    enums=(enums or {}).get(step.id),
                )
                served.append(_on_part(result, part))
                reproduced.append(
                    (
                        step.id,
                        document,
                        step.schema_hash is not None,
                        _as_text(result).encode(),
                        cache.record(key),
                        None if part is None else part[0],
                    )
                )
            if step.mode == "per_part":
                # What a later step reads is the document, not its pages
                # (R3.12) -- and what `dossier eval` scores is the document
                # too, with every page's records and checks on it (R6.15).
                every_part.extend(served)
                results.append(_joined_parts(served, document=document))
            else:
                results.extend(served)
        steps.append(
            StepReport(
                step=step.id,
                results=tuple(results),
                parts=tuple(every_part),
                unit="group" if step.mode == "per_group" else "document",
            )
        )
        produced[step.id] = {
            result.document: _as_text(result) for result in results if not result.failed
        }

    if destination is not None:
        for step_id, document, structured, payload, record, part in reproduced:
            _publish(
                run_dir=destination,
                step=step_id,
                document=document,
                structured=structured,
                payload=payload,
                record=record,
                part=part,
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
    reference: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
    cache: ArtifactStore,
    part: tuple[str, ImagePart] | None = None,
    enums: Mapping[str, Sequence[str]] | None = None,
) -> tuple[DocumentResult, str]:
    """One (step, document, part), served from the entry the original run wrote.

    The key is recomposed from the manifest and from what the earlier steps of
    *this replay* produced -- never from anything read out of the workspace
    today. It is therefore the same key the original computation used, or the
    entry is not found and the replay says so rather than pretending.

    The part is in the key exactly as `_run_one` put it there, and leaving it
    out was what made every `per_part` run irreproducible: the key built here
    was one no run had ever written, so the entry was always absent and the
    replay always stopped (R4.14).
    """
    contents = [
        _replayed_input(
            target=target,
            document=document,
            documents=documents,
            aggregate=_reads_a_set(step.mode),
            document_text=document_text,
            reference=reference,
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
            ]
            # Exactly as `_run_one` appended it. Leaving it out was what made
            # every per_part run irreproducible (R4.14).
            + (
                []
                if part is None
                else [
                    ArtifactInput(
                        role="part",
                        path=f"part/{document}/{part[0]}",
                        hash=content_hash(part[1].data),
                    )
                ]
            )
            # Exactly as `_run_one` appended it, for the reason the part is: a
            # key built without it is one no run wrote (R5.14 row 5, R4.15).
            + _group_input(step.mode, document),
        )
    )

    stored = cache.get(key, require_record=True)
    if stored is None:
        named = document if part is None else f"{document} {part[0]}"
        raise MissingFromReplay(
            f"step {step.id!r} has no cached artifact for {named!r} "
            f"at {key[:12]}...; this run cannot be reproduced from this "
            "workspace, and nothing has been substituted for it."
        )

    served = _from_cache(
        document=document,
        payload=stored,
        # Checked against what the call was shown, as the run checked it: a
        # replay that checked it against more would pass a citation the run
        # refused, and `dossier eval` scores the replay (R6.22, R6.23).
        document_text=_citable(
            mode=step.mode,
            document=document,
            documents=documents,
            targets=step.inputs,
            document_text=document_text,
            reference=reference,
        ),
        # The replay knows which documents this stage was shown as pictures,
        # exactly as the run did, so a described field is reproduced described
        # rather than ungrounded -- and `dossier eval` scores what the run
        # produced rather than a harsher reading of it (R6.15).
        shown_as_pictures=() if part is None else (document,),
        structured=step.schema_hash is not None,
        enums=enums,
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


def _replayed_parts_for(
    *,
    step: ResolvedStep,
    document: str,
    by_part: Mapping[str, Mapping[str, Sequence[tuple[str, ImagePart]]]],
) -> list[tuple[str, ImagePart] | None]:
    """The parts one replayed call of this step runs over, or `[None]` for one.

    `_parts_for`'s shape, reading the manifest's resolved inputs rather than the
    declared ones -- and with one difference that matters: a `per_part` document
    with no parts is an empty list there, meaning the run never ran it, and here
    it is a *failure*. The run produced artifacts for those pages, so a replay
    that quietly produced none would report a smaller run than happened (R4.14).
    """
    if step.mode != "per_part":
        return [None]

    for target in step.inputs:
        _, kind = split_kind(target)
        if kind is None:
            continue
        found = by_part.get(kind, {}).get(document)
        if found:
            return list(found)

    raise MissingFromReplay(
        f"step {step.id!r} is mode: per_part and no parts could be reproduced for "
        f"{document!r}; this run cannot be reproduced from this workspace, and "
        "nothing has been substituted for it."
    )


def _replayed_input(
    *,
    target: str,
    document: str,
    documents: Sequence[str],
    aggregate: bool,
    document_text: Mapping[str, str],
    reference: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
) -> str:
    """The content behind one resolved input id, for this document.

    The same content `execute` hashed, obtained the same way. `role` and `path`
    do not enter a key (spec 005), so a replay needs the resolved ids and not the
    declared names the prompt used -- which is fortunate, because a manifest
    records the former and the whole point is that it is enough.
    """
    # The kind comes off before asking what this names, as it does in
    # `_input_values`: `documents@page_images` is a source keyword with a kind
    # (R3.11), and reading it as a step id would hash an empty string for a
    # reason that happens to give the same answer, which is not the same as
    # being right.
    name, kind = split_kind(target)
    if name == REFERENCE:
        # Every reference document, as `_input_values` rendered it (R3.18),
        # and nothing for a kind that is not text, as there.
        held = reference if kind in (None, DEFAULT_INPUT_KIND) else {}
        return _joined(held, list(held))
    if name not in SOURCE_KEYWORDS:
        source = produced.get(target, {})
    elif kind in (None, DEFAULT_INPUT_KIND):
        source = document_text
    else:
        # A non-text kind reaches a step as parts, never as a substitution, so
        # `execute` hashed an empty string for it here too (R8.11).
        source = {}
    return _one_value(source, document=document, documents=documents, aggregate=aggregate)
