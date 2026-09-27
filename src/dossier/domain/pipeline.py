"""The shape of a configuration, and the checks that need nothing but it (spec 003).

Models and pure validators. Reading YAML, resolving paths and opening schema
files all belong to `dossier.config`; what is here can be checked with a value
in hand and no filesystem, which is why R3.2 and R3.3 name this layer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

# `documents` and `reference` name sources, not steps. A step may read them
# without any step having produced them (spec 003).
# The documents a pipeline audits, which a per-document step runs over one at a
# time (R6.21 asks whether each holds anything the step reads).
DOCUMENTS = "documents"
# The documents a pipeline reads as context: shown whole to every call that
# reads them, and never audited (R3.17, R3.18).
REFERENCE = "reference"
SOURCE_KEYWORDS = frozenset({DOCUMENTS, REFERENCE})

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

# A key of a `convert:` map: `type/subtype`, as a snapshot records it (R2.16).
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


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
    # be -- which is the normal case for a folder of notes. A list is asked of
    # every document; a map only of the media types it names (R8.26).
    convert: list[str] | dict[str, list[str]] | None = None
    # How far before its last sync a source asks from (R2.4). Shared by every
    # type, so the core checks it and no connector has to declare it (R1.10).
    # `None` is "not said", and the default applies.
    watermark_overlap: timedelta | None = None
    # The keys that belong to this source's type -- a folder's `path`, a Jira
    # source's `query` -- as its connector declared and checked them (R1.10).
    # Held here rather than as fields because the core may not name them: every
    # new source type would otherwise be an edit to this model (R1.7).
    options: dict[str, Any] = {}

    @field_validator("convert")
    @classmethod
    def _media_types_as_keys(
        cls, value: list[str] | dict[str, list[str]] | None
    ) -> list[str] | dict[str, list[str]] | None:
        """A map's keys are media types, never file extensions (R8.26 row 6).

        The snapshot's media type selects a converter (R8.3). A key that is not
        one would match no document, and every document it was meant for would
        quietly get its default kind instead.
        """
        if not isinstance(value, dict):
            return value
        if not value:
            raise ValueError(
                "an empty map declares nothing. Omit convert: to get the default "
                "kind for each document's media type (R8.10)."
            )
        # `[]` under a key is allowed: that media type is not read (R8.27).
        for media_type in value:
            if not _MEDIA_TYPE.match(media_type):
                raise ValueError(
                    f"convert: maps media types to kinds, and {media_type!r} is not a "
                    "media type. Write it as a snapshot records it, such as "
                    "application/pdf: a file extension is not evidence about content "
                    "(R8.3, R8.26)."
                )
        return value

    @field_validator("fields", "convert")
    @classmethod
    def _reject_empty_list(cls, value: list[str] | None) -> list[str] | None:
        if isinstance(value, list) and not value:
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
    # `per_group` asks once per group of documents sharing a key's first segment:
    # a contract and its amendments, an issue and its attachments (R3.15).
    mode: Literal["per_file", "aggregate", "per_part", "per_group"]
    output: str | None = None
    # The model this step is asked with instead of the pipeline's (R3.14).
    # `None` is the pipeline's: most steps name none, and one that names the
    # pipeline's own model is the same step.
    model: str | None = None

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


def validate_modes(pipeline: PipelineConfig) -> None:
    """R3.12 -- a `per_part` step reads an input that has parts; R3.16 -- only a
    `per_group` or `aggregate` step reads a `per_group` step.

    Decidable from the configuration alone: a kind is written on the input
    (R3.11), and the text kind has no parts to fan out over. Refusing it here
    rather than at the first call means the author hears about it before a
    single page is rendered.

    A step id cannot be `per_part` either, and for the same reason: another
    step's output is one artifact per document, not a container.
    """
    for step in pipeline.steps:
        if step.mode != "per_part":
            continue
        for declared in step.inputs:
            if is_relative_reference(declared):
                name, kind = declared, None
            else:
                name, kind = split_kind(declared)
            if kind is None or kind == DEFAULT_INPUT_KIND:
                raise ValueError(
                    f"step {step.id!r} is mode: per_part and reads {declared!r}, "
                    "which has no parts to run over. A per_part step reads a "
                    "converted kind that produces several artifacts per document, "
                    "such as documents@page_images (R3.12)."
                )

    # R3.16 -- a `per_group` step's outputs are named for groups, so only a step
    # that reads a set can read them: another `per_group` step, which reads its
    # own group's, or an `aggregate` one, which reads every group's. A `per_file`
    # step would be asked about `ACME-2024/master.pdf` and handed either the
    # group's answer, about three documents, or none at all.
    order = [step.id for step in pipeline.steps]
    modes = {step.id: step.mode for step in pipeline.steps}
    for position, step in enumerate(pipeline.steps):
        if step.mode in ("per_group", "aggregate"):
            continue
        for declared in step.inputs:
            for read in _step_ids_read(declared, preceding=order[:position]):
                if modes.get(read) == "per_group":
                    raise ValueError(
                        f"step {step.id!r} is mode: {step.mode} and reads {read!r}, "
                        "which is mode: per_group and answers once per group. Only a "
                        "per_group or aggregate step can read it (R3.16)."
                    )


def _step_ids_read(declared: str, *, preceding: list[str]) -> list[str]:
    """The step ids one declared input reads, `previous` sugar included.

    `previous(n)` is the `n` steps before this one (R4.2). Taken by position
    here, and only as many as exist: asking for more than precede the step is
    R4.3's refusal, made at resolution with its own message.
    """
    match = _RELATIVE_REFERENCE.match(declared)
    if match is None:
        return [declared]
    count = 1 if match.group("n") is None else int(match.group("n"))
    return preceding[-count:] if count else []


def reads_reference(inputs: Sequence[str]) -> bool:
    """Whether a step reads the `reference:` documents, under any kind (R3.18)."""
    return any(split_kind(name)[0] == REFERENCE for name in inputs)


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
            if reference == REFERENCE and not pipeline.reference:
                # `{{reference}}` would hold nothing, and the prompt around it
                # would still call that nothing the context (R3.18 row 4).
                raise ValueError(
                    f"step {step.id!r} reads 'reference', but the pipeline declares "
                    "no `reference:` sources for it to hold. Name them under "
                    "`reference:`, or remove the input."
                )
            if reference not in available:
                raise ValueError(
                    f"step {step.id!r} reads {reference!r}, which is not available at "
                    f"that point. Available: {sorted(available)}. A step may only read "
                    "a source keyword or a step declared before it."
                )
        # Added after its own inputs are checked, which is what makes a
        # self-reference an error rather than a silent no-op.
        available.add(step.id)
