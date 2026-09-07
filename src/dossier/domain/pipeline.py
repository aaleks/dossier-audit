"""The shape of a configuration, and the checks that need nothing but it (spec 003).

Models and pure validators. Reading YAML, resolving paths and opening schema
files all belong to `dossier.config`; what is here can be checked with a value
in hand and no filesystem, which is why R3.2 and R3.3 name this layer.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

# `documents` and `reference` name sources, not steps. A step may read them
# without any step having produced them (spec 003).
SOURCE_KEYWORDS = frozenset({"documents", "reference"})

_STEP_ID = re.compile(r"^[a-z][a-z0-9_]*$")

# `previous` and `previous(n)` are sugar for "the step(s) before this one". They
# are not ids and nothing here can resolve them: this layer sees one pipeline
# with no notion of a run. Spec 004 expands them, and R4.3 is where "previous
# with nothing preceding it" becomes an error.
_RELATIVE_REFERENCE = re.compile(r"^previous(\((?P<n>\d+)\))?$")


def is_relative_reference(reference: str) -> bool:
    """Whether an input is `previous` sugar rather than a concrete id (R4.2)."""
    return _RELATIVE_REFERENCE.match(reference) is not None


class SourceConfig(BaseModel):
    """One entry under `sources:`."""

    # Unknown keys are refused rather than ignored. A typo that is silently
    # dropped is a source configured differently from what its author wrote,
    # discovered as a document that never syncs (R3.1).
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    type: str
    path: str | None = None
    fields: list[str] | None = None

    @field_validator("fields")
    @classmethod
    def _reject_empty_projection(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not value:
            # Absent and empty are different declarations. Reading `[]` as "hash
            # everything" would give a source the opposite of what it asked for,
            # silently (R2.10, R3.9).
            raise ValueError(
                "fields is empty: a projection onto no fields matches nothing. "
                "Omit `fields` entirely to hash the payload as received."
            )
        return value


class StepConfig(BaseModel):
    """One entry under `steps:`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    prompt: str
    input: str | list[str]
    mode: Literal["per_file", "aggregate"]
    output: str | None = None

    @property
    def inputs(self) -> list[str]:
        """`input` as a list, however it was written.

        The YAML allows a bare string for the common single-input case. Every
        caller wants a list, and letting each one normalise would be four places
        to get it wrong.
        """
        return [self.input] if isinstance(self.input, str) else list(self.input)


class PipelineConfig(BaseModel):
    """One `pipelines/<name>/pipeline.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    sources: list[str]
    reference: list[str] = []
    gold: str | None = None
    model: str
    steps: list[StepConfig]

    @property
    def synced_sources(self) -> list[str]:
        """Every source this pipeline needs held before it can run (R2.12).

        Reference documents are inputs like any other -- a pipeline cannot verify
        against a procedure it has not fetched -- so they sync too.
        """
        return [*self.sources, *self.reference]


def validate_step_ids(pipeline: PipelineConfig) -> None:
    """R3.2 — unique, and shaped so they can be directory names and key inputs."""
    seen: set[str] = set()
    for step in pipeline.steps:
        if not _STEP_ID.match(step.id):
            raise ValueError(
                f"step id {step.id!r} must match [a-z][a-z0-9_]*. "
                "Step ids become directory names and appear in cache keys."
            )
        if step.id in seen:
            raise ValueError(f"duplicate step id {step.id!r}")
        seen.add(step.id)


def validate_references(pipeline: PipelineConfig) -> None:
    """R3.3 — a step may only read a source keyword or an earlier step."""
    available: set[str] = set(SOURCE_KEYWORDS)
    for step in pipeline.steps:
        for reference in step.inputs:
            if is_relative_reference(reference):
                # Not an id, so there is nothing to look up. Rejecting it here
                # would make every rule in spec 004 unreachable through the CLI:
                # no pipeline written with the sugar could ever be loaded.
                continue
            if reference not in available:
                raise ValueError(
                    f"step {step.id!r} reads {reference!r}, which is not available at "
                    f"that point. Available: {sorted(available)}. A step may only read "
                    "a source keyword or a step declared before it."
                )
        # Added after its own inputs are checked, which is what makes a
        # self-reference an error rather than a silent no-op.
        available.add(step.id)
