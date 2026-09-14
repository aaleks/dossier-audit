"""Reading `sources.yaml` and `pipeline.yaml` from disk (spec 003).

Loading is a pure function of files on disk: no network, no model calls, no
credentials looked up (R3.8). An invalid file is a hard error here, before any
work begins, because everything downstream is expensive and a configuration
mistake is cheap to catch now.

The *shapes*, and the checks that need nothing but a value in hand, live in
`dossier.domain.pipeline` -- R3.2 and R3.3 name that layer. What is here is the
part that touches the filesystem: reading YAML, resolving paths against the
pipeline directory, and opening the field declaration a step's `output` names
(R3.10).

This is the only package that may read `os.environ`, and it does not do so while
loading -- a connector asks for its credential when it is actually used (R1.8).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from dossier.domain.fields import OutputSchema, declare_fields, json_schema
from dossier.domain.hashing import text_hash
from dossier.domain.pipeline import (
    PipelineConfig,
    SourceConfig,
    validate_references,
    validate_step_ids,
)
from dossier.domain.prompts import check_placeholders
from dossier.domain.scoring import FieldKind

__all__ = [
    "ConfigError",
    "PipelineConfig",
    "SourceConfig",
    "load_fields",
    "load_output_schema",
    "load_pipeline",
    "load_sources",
]


class ConfigError(Exception):
    """A configuration file is unusable, and the message says which and why.

    Its own type rather than pydantic's: a caller in `cli/` needs to tell a bad
    configuration from a bug, and R3.1 makes the content of this message an
    interface rather than an implementation detail.
    """


def load_sources(path: Path) -> list[SourceConfig]:
    """Every source declared in `sources.yaml`, validated."""
    document = _read_yaml(path)

    raw = document.get("sources")
    if not isinstance(raw, list):
        raise ConfigError(f"{_name(path)}: expected a `sources:` list")

    sources = [_validate(SourceConfig, entry, path) for entry in raw]
    _reject_duplicate_ids(sources, path)
    return sources


def load_pipeline(path: Path) -> PipelineConfig:
    """Load and validate one pipeline, with its schemas.

    Relative paths inside the file are resolved against the pipeline's own
    directory, so a pipeline is self-contained and can be moved.
    """
    document = _read_yaml(path)
    document["name"] = path.parent.name

    pipeline = _validate(PipelineConfig, document, path)

    # The pure checks live in domain and raise ValueError; this layer is what
    # knows which file the value came out of.
    for check in (validate_step_ids, validate_references):
        try:
            check(pipeline)
        except ValueError as error:
            raise ConfigError(f"{_name(path)}: {error}") from error

    _validate_output_declarations(pipeline, path)
    _validate_prompt_placeholders(pipeline, path)
    return pipeline


def load_fields(path: Path) -> dict[str, FieldKind]:
    """The fields one declaration states, and each one's kind (R6.10).

    Reading and parsing is this layer's job; whether the declaration can be
    scored is the domain's.
    """
    document = _read_yaml(path)
    try:
        return declare_fields(document)
    except ValueError as error:
        raise ConfigError(f"{_name(path)}: {error}") from error


def load_output_schema(path: Path) -> OutputSchema:
    """What one declaration contributes to a run (R6.10, R6.11).

    The schema shown to the model is generated from the declaration. The key
    takes the declaration's own text, hashed the way spec 005 hashes every
    configuration file -- so an edit the generated schema cannot see still moves
    the key.
    """
    return OutputSchema(schema=json_schema(load_fields(path)), declaration_hash=text_hash(path))


def _validate_prompt_placeholders(pipeline: PipelineConfig, path: Path) -> None:
    """R3.6 — every prompt injects exactly the inputs its step declares.

    Reading the file is this layer's job; deciding whether the two sides agree is
    the domain's. The prompt is read as bytes-decoded text and not otherwise
    touched, because its hash is part of that stage's key (R5.2).
    """
    for step in pipeline.steps:
        prompt = path.parent / step.prompt
        if not prompt.is_file():
            raise ConfigError(
                f"{_name(path)}: step {step.id!r} names a prompt that does not "
                f"exist: {step.prompt}"
            )
        try:
            check_placeholders(
                step=step.id,
                declared=step.inputs,
                prompt=prompt.read_text(encoding="utf-8"),
            )
        except ValueError as error:
            raise ConfigError(f"{_name(path)}: {error}") from error


def _validate_output_declarations(pipeline: PipelineConfig, path: Path) -> None:
    """R3.10 — every `output` is a field declaration that loads and declares valid kinds.

    Checked here, before anything runs: a declaration that cannot be read is a
    pipeline that cannot be scored, and finding that out after a run has been
    paid for is the failure this exists to prevent.
    """
    for step in pipeline.steps:
        if step.output is None:
            # An `aggregate` step may produce prose. No declaration, no check --
            # and no scoring for that step (R3.10 row 5).
            continue
        declaration = path.parent / step.output
        if not declaration.is_file():
            raise ConfigError(
                f"{_name(path)}: step {step.id!r} declares output {step.output!r}, "
                f"which does not exist ({declaration})"
            )
        try:
            load_fields(declaration)
        except ConfigError as error:
            raise ConfigError(f"{_name(path)}: step {step.id!r}: {error}") from error


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
