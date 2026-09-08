"""Executing a pipeline (spec 004).

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

Nothing here constructs a model client, opens a connector or reads a clock.
Every one of those arrives as an argument, which is what lets the whole path run
against `FakeModelClient` and lets the tests assert how many calls happened.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dossier.application.extract import DocumentResult, run_stage
from dossier.application.manifest import Manifest
from dossier.domain.pipeline import PipelineConfig, validate_references, validate_step_ids
from dossier.domain.ports import ModelClient
from dossier.domain.resolution import resolve

# (step id, document key) -> the prompt that stage should send for that document.
#
# A callable rather than a mapping of rendered strings, because rendering is
# R3.6's question -- placeholders and declared inputs corresponding exactly --
# and that rule is not built. Making it a seam keeps this module from inventing a
# templating convention nobody agreed to, and leaves one obvious place to put the
# real one.
PromptFor = Callable[[str, str], str]


@dataclass(frozen=True)
class StepReport:
    """What one step produced, per document, in document order."""

    step: str
    results: tuple[DocumentResult, ...] = ()

    @property
    def failed(self) -> tuple[DocumentResult, ...]:
        return tuple(result for result in self.results if result.failed)


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


def execute(
    *,
    workspace: Path,
    pipeline: PipelineConfig,
    pipeline_hash: str,
    documents: Mapping[str, str],
    document_text: Mapping[str, str],
    schemas: Mapping[str, dict],
    prompt_for: PromptFor,
    model: ModelClient,
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
    steps = tuple(
        StepReport(
            step=step.id,
            results=tuple(
                run_stage(
                    document=key,
                    prompt=prompt_for(step.id, key),
                    schema=schemas[step.id],
                    model=model,
                    input_documents=document_text,
                )
                for key in keys
            ),
        )
        for step in plan.steps
    )

    return RunReport(run_id=run_id, manifest_path=manifest, steps=steps)


def _resolve(*, pipeline: PipelineConfig, pipeline_hash: str, documents: Mapping[str, str]):
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
