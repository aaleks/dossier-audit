"""The shape of a configuration, and the checks that need nothing but it (spec 003).

Models and pure validators. Reading YAML, resolving paths and opening schema
files all belong to `dossier.config`; what is here can be checked with a value
in hand and no filesystem, which is why R3.2 and R3.3 name this layer.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Literal

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


# `24h`, `48h`, `0h`: the only form the specs use (spec 003, R2.4). Hours alone,
# because a unit that has to be guessed is how an overlap ends up a different
# length from the one its author wrote.
_DURATION = re.compile(r"^(\d+)h$")


class SourceConfig(BaseModel):
    """One entry under `sources:`."""

    # Unknown keys are refused rather than ignored. A typo that is silently
    # dropped is a source configured differently from what its author wrote,
    # discovered as a document that never syncs (R3.1).
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    type: str
    fields: list[str] | None = None
    # Which conversions this source wants (spec 003, and R8.3's `kinds`). Absent
    # means the default kind for whatever media type each document turns out to
    # be -- which is the normal case for a folder of notes.
    convert: list[str] | None = None
    # How far before its last sync a source asks from (R2.4). Shared by every
    # type, so the core checks it and no connector has to declare it (R1.10).
    # `None` is "not said", and the default applies.
    watermark_overlap: timedelta | None = None
    # The keys that belong to this source's type -- a folder's `path`, a Jira
    # source's `query` -- as its connector declared and checked them (R1.10).
    # Held here rather than as fields because the core may not name them: every
    # new source type would otherwise be an edit to this model (R1.7).
    options: dict[str, Any] = {}

    @field_validator("fields", "convert")
    @classmethod
    def _reject_empty_list(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not value:
            # Absent and empty are different declarations, for both of these.
            # Reading `[]` as "hash everything" or "convert to everything" gives
            # a source the opposite of what it asked for, silently (R2.10, R3.9).
            raise ValueError(
                "an empty list matches nothing. Omit the key entirely to get the "
                "default: the payload hashed as received, or the default kind for "
                "the media type."
            )
        return value

    @field_validator("watermark_overlap", mode="before")
    @classmethod
    def _parse_duration(cls, value: object) -> object:
        """`24h` as a duration. A bare number is refused rather than read.

        `24` has no unit. Pydantic would take it as seconds, and a day's overlap
        would silently become twenty-four seconds of one (R3.1 row 3).
        """
        if value is None or isinstance(value, timedelta):
            return value
        if isinstance(value, bool | int | float):
            raise ValueError("a duration such as 24h, not a bare number")
        match = _DURATION.match(str(value).strip())
        if match is None:
            raise ValueError(f"{value!r} is not a duration; write it in hours, such as 24h")
        return timedelta(hours=int(match.group(1)))


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


# What separates an input from the kind it reads (R3.11). `@` rather than `:` or
# `.`: `:` already separates a provider from a model (spec 009), a bare `.` reads
# as an attribute of something, and `@` already means "qualified by" in this
# project -- `hf:Qwen/Qwen2.5-7B@1c0f8e6b`.
KIND_SEPARATOR = "@"

# What a source keyword resolves to when no kind is written. `markdown` because
# a stage reads text and grounding searches converted text (R6.4), and because
# every pipeline written before R3.11 says `documents` and must keep meaning
# exactly what it meant.
#
# Deliberately not `conversion.default_kind`: that answers "what should this
# media type be converted to", which is a question about bytes. This answers
# "what does an unqualified input mean", which is a question about the pipeline
# language. They agree today for text and would diverge the moment a source of
# PNGs made `documents` mean `page_images` for one pipeline and not another.
DEFAULT_INPUT_KIND = "markdown"


def split_kind(reference: str) -> tuple[str, str | None]:
    """An input split into what it names and the kind it reads (R3.11).

    The kind is `None` for a step id: a step's output is not a conversion, so it
    has no media type, no converter and no kind to pick. Returning the default
    there would be inventing a property the artifact does not have.
    """
    name, separator, kind = reference.partition(KIND_SEPARATOR)

    if not separator:
        return (name, DEFAULT_INPUT_KIND if name in SOURCE_KEYWORDS else None)

    if name not in SOURCE_KEYWORDS:
        raise ValueError(
            f"step input {reference!r} names a kind on {name!r}, which is not a "
            f"source. Only {sorted(SOURCE_KEYWORDS)} read a conversion; a step id "
            "names another step's output, which has no kind to choose (R3.11)."
        )

    if not kind:
        raise ValueError(
            f"step input {reference!r} ends in {KIND_SEPARATOR!r} with no kind after "
            f"it. Write the kind, or drop the {KIND_SEPARATOR!r} to read "
            f"{DEFAULT_INPUT_KIND!r} (R3.11)."
        )

    return (name, kind)


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
            # The kind an input reads is checked against what its sources make,
            # which is a resolution question (R4.13). What is checked here is
            # only that the thing being read exists -- so the kind is split off
            # first, and `documents@page_images` is looked up as `documents`.
            #
            # Split rather than stripped: split_kind is also what refuses a kind
            # on a step id, and doing that here rather than later is what makes
            # it a load-time error naming the file (R3.1).
            reference, _ = split_kind(reference)
            if reference not in available:
                raise ValueError(
                    f"step {step.id!r} reads {reference!r}, which is not available at "
                    f"that point. Available: {sorted(available)}. A step may only read "
                    "a source keyword or a step declared before it."
                )
        # Added after its own inputs are checked, which is what makes a
        # self-reference an error rather than a silent no-op.
        available.add(step.id)
