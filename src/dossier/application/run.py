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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dossier.application.extract import DocumentResult, run_stage
from dossier.application.manifest import Manifest
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
from dossier.domain.ports import ArtifactStore, ModelClient
from dossier.domain.prompts import render
from dossier.domain.resolution import ResolvedPlan, ResolvedStep, resolve
from dossier.domain.schemas import StageOutput


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
            (report.step, result.document)
            for report in self.steps
            for result in report.failed
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
    document_text: Mapping[str, str],
    schemas: Mapping[str, dict],
    prompts: Mapping[str, str],
    model: ModelClient,
    cache: ArtifactStore,
    run_id: str,
    started_at: datetime,
    dossier_version: str,
) -> RunReport:
    """Resolve the pipeline, freeze it, then run it.

    Raises `ValueError` if resolution fails, having written nothing and called
    nothing. Returns a report if it succeeded, whatever individual documents did.
    """
    plan = _resolve(pipeline=pipeline, pipeline_hash=pipeline_hash, documents=documents)

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

    for step in plan.steps:
        results = tuple(
            _run_one(
                step=step,
                declared=declared[step.id],
                document=key,
                document_text=document_text,
                produced=produced,
                schema=schemas[step.id],
                prompt=prompts[step.id],
                model=model,
                cache=cache,
                run_id=run_id,
                dossier_version=dossier_version,
            )
            for key in keys
        )
        steps.append(StepReport(step=step.id, results=results))
        produced[step.id] = {
            result.document: _as_text(result) for result in results if not result.failed
        }

    return RunReport(run_id=run_id, manifest_path=manifest, steps=tuple(steps))


def _as_text(result: DocumentResult) -> str:
    """One step's output: the artifact it is cached as, and the text below it reads.

    Serialised from the validated records rather than from the model's raw reply,
    so a cache hit and a fresh run produce the same bytes even where the model
    answered with different whitespace (R5.5).
    """
    return StageOutput(
        document=result.document, fields=list(result.records)
    ).model_dump_json()


def _run_one(
    *,
    step: ResolvedStep,
    declared: StepConfig,
    document: str,
    document_text: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
    schema: dict,
    prompt: str,
    model: ModelClient,
    cache: ArtifactStore,
    run_id: str,
    dossier_version: str,
) -> DocumentResult:
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
        document_text=document_text,
        produced=produced,
    )
    key_inputs = StageInputs(
        step=step.id,
        prompt=ArtifactInput(
            role="prompt", path=declared.prompt, hash=content_hash(prompt.encode())
        ),
        output_schema=ArtifactInput(
            role="schema",
            path=declared.output or "",
            hash=content_hash(json.dumps(schema, sort_keys=True).encode()),
        ),
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
        return _from_cache(document=document, payload=hit, document_text=document_text)

    result = run_stage(
        document=document,
        prompt=render(prompt, values),
        schema=schema,
        model=model,
        input_documents=document_text,
    )

    if not result.failed:
        # A failed document is deliberately not cached. It is a recorded
        # per-document failure rather than a computed artifact, and caching it
        # would make one bad afternoon permanent (R6.1, R6.9, R5.8 row 4).
        cache.put(
            key,
            _as_text(result).encode(),
            record=provenance(
                key_inputs, run_id=run_id, dossier_version=dossier_version, step=step.id
            ),
        )
    return result


def _from_cache(
    *, document: str, payload: bytes, document_text: Mapping[str, str]
) -> DocumentResult:
    """Rebuild what a cached artifact stands for, with no model call.

    Grounding is re-derived rather than stored alongside. It is a pure function
    of the artifact and the documents (R6.4), so re-deriving costs microseconds
    and removes a second thing that could go stale.
    """
    output = StageOutput.model_validate_json(payload.decode())
    checks = tuple(
        check_field(record, input_documents=document_text) for record in output.fields
    )
    return DocumentResult(
        document=document, records=tuple(output.fields), checks=checks, attempts=0
    )


def _input_values(
    *,
    declared: StepConfig,
    resolved: ResolvedStep,
    document: str,
    document_text: Mapping[str, str],
    produced: Mapping[str, Mapping[str, str]],
) -> dict[str, str]:
    """What each declared input holds, for this document.

    Keyed by the name the *prompt* uses, which is the name as declared -- sugar
    included, because that is the form R3.6 checked at load time. The resolved
    ids say where the content comes from.
    """
    values: dict[str, str] = {}
    for name, target in zip(declared.inputs, _targets(declared, resolved), strict=True):
        if target in SOURCE_KEYWORDS:
            values[name] = document_text.get(document, "")
        else:
            values[name] = produced.get(target, {}).get(document, "")
    return values


def _targets(declared: StepConfig, resolved: ResolvedStep) -> list[str]:
    """The resolved id behind each declared input, positionally.

    `previous(n)` for n > 1 expands one declared name into several ids, and there
    is no agreed way to join several under one placeholder: spec 003 says
    multiple inputs go under distinct labelled tags, which is a statement about
    declared inputs. Refused rather than guessed.
    """
    if len(declared.inputs) != len(resolved.inputs):
        raise ValueError(
            f"step {resolved.id!r} declares {len(declared.inputs)} input(s) that expand "
            f"to {len(resolved.inputs)}. `previous(n)` for n > 1 has no agreed "
            "rendering: spec 003 puts multiple inputs under distinct labelled tags, "
            "and one placeholder cannot carry several."
        )
    return list(resolved.inputs)


def _resolve(
    *, pipeline: PipelineConfig, pipeline_hash: str, documents: Mapping[str, str]
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
    _refuse_unimplemented_modes(pipeline)
    return resolve(pipeline=pipeline, pipeline_hash=pipeline_hash, documents=documents)


def _refuse_unimplemented_modes(pipeline: PipelineConfig) -> None:
    """`aggregate` is declared in spec 003 and not built here.

    Refused during resolution rather than ignored during execution. This loop
    runs every step over every document, which *is* `per_file`; an aggregate step
    reaching it would silently become one model call per document instead of one
    over all of them -- a different question asked of the model, a different bill,
    and an answer that looks entirely normal.

    Refusing here makes it a resolution failure, so nothing runs and no run
    directory appears (R4.1), which is the right shape for "this pipeline cannot
    be executed as written".
    """
    aggregate = [step.id for step in pipeline.steps if step.mode == "aggregate"]
    if aggregate:
        raise ValueError(
            f"steps {aggregate} declare mode 'aggregate', which is not implemented. "
            "Only 'per_file' runs today; an aggregate step would silently become "
            "one call per document."
        )
