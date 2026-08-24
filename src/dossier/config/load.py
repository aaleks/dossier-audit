"""Reading `sources.yaml` and `pipeline.yaml` (spec 003).

Loading is a pure function of files on disk: no network, no model calls, no
credentials looked up (R3.8). An invalid file is a hard error here, before any
work begins, because everything downstream is expensive and a configuration
mistake is cheap to catch now.

This is the only package that may read `os.environ`, and it does not do so while
loading -- a connector asks for its credential when it is actually used (R1.8).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class ConfigError(Exception):
    """A configuration file is unusable, and the message says which and why.

    Its own type rather than pydantic's: a caller in `cli/` needs to tell a bad
    configuration from a bug, and R3.1 makes the content of this message an
    interface rather than an implementation detail.
    """


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


def load_sources(path: Path) -> list[SourceConfig]:
    """Every source declared in `sources.yaml`, validated."""
    document = _read_yaml(path)

    raw = document.get("sources")
    if not isinstance(raw, list):
        raise ConfigError(f"{_name(path)}: expected a `sources:` list")

    sources = []
    for entry in raw:
        sources.append(_validate(SourceConfig, entry, path))

    _reject_duplicate_ids(sources, path)
    return sources


def _reject_duplicate_ids(sources: list[SourceConfig], path: Path) -> None:
    seen: set[str] = set()
    for source in sources:
        if source.id in seen:
            # The ledger is keyed by (source_id, key). Two sources sharing an id
            # would interleave their rows and neither would be correct.
            raise ConfigError(
                f"{_name(path)}: duplicate source id {source.id!r}. "
                "Source ids key the ledger and must be unique."
            )
        seen.add(source.id)


def _read_yaml(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(f"{_name(path)}: no such file ({path})") from error

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigError(f"{_name(path)}: not valid YAML -- {error}") from error

    if document is None:
        raise ConfigError(f"{_name(path)}: file is empty")
    if not isinstance(document, dict):
        raise ConfigError(f"{_name(path)}: expected a mapping at the top level")
    return document


def _validate[T: BaseModel](model: type[T], entry: object, path: Path) -> T:
    try:
        return model.model_validate(entry)
    except ValidationError as error:
        raise ConfigError(f"{_name(path)}: {_describe(error, entry)}") from error


def _describe(error: ValidationError, entry: object) -> str:
    identifier = entry.get("id") if isinstance(entry, dict) else None
    where = f"in {identifier!r}: " if identifier else ""
    problems = "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or '(root)'} -- {problem['msg']}"
        for problem in error.errors()
    )
    return where + problems


def _name(path: Path) -> str:
    return path.name


class StepConfig(BaseModel):
    """One entry under `steps:` (spec 003)."""

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


# `documents` and `reference` name sources, not steps. A step may read them
# without any step having produced them (spec 003).
SOURCE_KEYWORDS = frozenset({"documents", "reference"})

_STEP_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def load_pipeline(path: Path) -> PipelineConfig:
    """Load and validate one pipeline, with its schemas.

    Relative paths inside the file are resolved against the pipeline's own
    directory, so a pipeline is self-contained and can be moved.
    """
    document = _read_yaml(path)
    document["name"] = path.parent.name

    pipeline = _validate(PipelineConfig, document, path)

    _validate_step_ids(pipeline, path)
    _validate_references(pipeline, path)
    _validate_output_schemas(pipeline, path)
    return pipeline


def _validate_step_ids(pipeline: PipelineConfig, path: Path) -> None:
    """R3.2 — unique, and shaped so they can be directory names and key inputs."""
    seen: set[str] = set()
    for step in pipeline.steps:
        if not _STEP_ID.match(step.id):
            raise ConfigError(
                f"{_name(path)}: step id {step.id!r} must match [a-z][a-z0-9_]*. "
                "Step ids become directory names and appear in cache keys."
            )
        if step.id in seen:
            raise ConfigError(f"{_name(path)}: duplicate step id {step.id!r}")
        seen.add(step.id)


def _validate_references(pipeline: PipelineConfig, path: Path) -> None:
    """R3.3 — a step may only read a source keyword or an earlier step."""
    available: set[str] = set(SOURCE_KEYWORDS)
    for step in pipeline.steps:
        for reference in step.inputs:
            if reference not in available:
                known = sorted(available)
                raise ConfigError(
                    f"{_name(path)}: step {step.id!r} reads {reference!r}, which is "
                    f"not available at that point. Available: {known}. "
                    "A step may only read a source keyword or a step declared before it."
                )
        # Added after its own inputs are checked, which is what makes a
        # self-reference an error rather than a silent no-op.
        available.add(step.id)


def _validate_output_schemas(pipeline: PipelineConfig, path: Path) -> None:
    """R3.5 — every declared output schema exists and parses."""
    for step in pipeline.steps:
        if step.output is None:
            # An `aggregate` step may produce prose. No schema means no check.
            continue
        schema = path.parent / step.output
        try:
            json.loads(schema.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ConfigError(
                f"{_name(path)}: step {step.id!r} declares output {step.output!r}, "
                f"which does not exist ({schema})"
            ) from error
        except json.JSONDecodeError as error:
            raise ConfigError(
                f"{_name(path)}: step {step.id!r} output schema {step.output!r} is not "
                f"valid JSON -- line {error.lineno}, column {error.colno}: {error.msg}"
            ) from error
