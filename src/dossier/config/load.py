"""Reading `sources.yaml` and `pipeline.yaml` (spec 003).

Loading is a pure function of files on disk: no network, no model calls, no
credentials looked up (R3.8). An invalid file is a hard error here, before any
work begins, because everything downstream is expensive and a configuration
mistake is cheap to catch now.

This is the only package that may read `os.environ`, and it does not do so while
loading -- a connector asks for its credential when it is actually used (R1.8).
"""

from __future__ import annotations

from pathlib import Path

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
