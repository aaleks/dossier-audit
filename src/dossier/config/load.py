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

import difflib
import json
from collections.abc import Collection, Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from dossier.domain.fields import OutputSchema, declare_fields, json_schema
from dossier.domain.gold import CalibrationCase, GoldDocument
from dossier.domain.grounding import DESCRIBED, GROUNDED, JUDGED_STATES
from dossier.domain.hashing import text_hash
from dossier.domain.model_id import check_pinned, provider_of
from dossier.domain.pipeline import (
    PipelineConfig,
    SourceConfig,
    validate_modes,
    validate_references,
    validate_step_ids,
)
from dossier.domain.prompts import check_placeholders
from dossier.domain.scoring import FieldKind

# The key a source names its credential's variable under, spelled once. Imported
# by `dossier.config.credentials`, which reads what it points at (R1.8).
TOKEN_ENV = "token_env"
# The key naming the variable holding the user a token is paired with, when the
# source is reached with HTTP Basic rather than a bearer token (R1.12). Generic
# for the reason `token_env` is: a user is not a Jira idea.
USER_ENV = "user_env"

__all__ = [
    "JUDGE_FILE",
    "ConfigError",
    "PipelineConfig",
    "SourceConfig",
    "load_calibration_sample",
    "load_fields",
    "load_judge_rubrics",
    "load_judge_thresholds",
    "load_output_schema",
    "load_output_schemas",
    "load_pipeline",
    "load_sources",
]


class ConfigError(Exception):
    """A configuration file is unusable, and the message says which and why.

    Its own type rather than pydantic's: a caller in `cli/` needs to tell a bad
    configuration from a bug, and R3.1 makes the content of this message an
    interface rather than an implementation detail.
    """


class _NoKeys(BaseModel):
    """What a connector that declares nothing accepts beyond the shared keys: nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# The keys every source has, whatever its type. Everything else is its
# connector's to declare (R1.10).
_SHARED = frozenset(SourceConfig.model_fields) - {"options"}


def load_sources(
    path: Path, *, connectors: Mapping[str, type[BaseModel] | None]
) -> list[SourceConfig]:
    """Every source declared in `sources.yaml`, checked against its connector's keys.

    `connectors` maps each installed source type to the keys model its connector
    declares (`None` for one that declares none). It is passed in because this
    layer may import only the domain, and the registry is infrastructure: the CLI
    builds it from the entry points, and a test passes one directly (R1.10).
    """
    document = _read_yaml(path)

    raw = document.get("sources")
    if not isinstance(raw, list):
        raise ConfigError(f"{_name(path)}: expected a `sources:` list")

    sources = [
        _validate_source(entry, index, path, connectors) for index, entry in enumerate(raw)
    ]
    _reject_duplicate_ids(sources, path)
    return sources


def _validate_source(
    entry: object,
    index: int,
    path: Path,
    connectors: Mapping[str, type[BaseModel] | None],
) -> SourceConfig:
    """One `sources:` entry: the shared keys checked here, the rest by its connector.

    A type's own keys -- a folder's `path` -- are known only to the connector
    that declares them, so a folder with no `path` is found now rather than at
    the first sync (R1.10). A problem with one of them is named where it is
    written (R3.1).
    """
    if not isinstance(entry, dict):
        return _validate(SourceConfig, entry, path)

    _reject_credentials(entry, index, path)

    try:
        config = SourceConfig.model_validate({k: v for k, v in entry.items() if k in _SHARED})
    except ValidationError as error:
        # Named at its line like any connector key: a wrong `watermark_overlap`
        # is as hard to find in a long file as a misspelt `path` (R3.1 row 3).
        raise _source_error(error, entry, index, path, known=_SHARED) from error
    own = {k: v for k, v in entry.items() if k not in _SHARED}

    if config.type not in connectors:
        # A source cannot be checked against a declaration that does not exist,
        # so an uninstalled type is found now rather than at the first sync
        # (R1.10 row 5).
        line = _line_of(path.read_text(encoding="utf-8"), "sources", index, "type")
        where = f", line {line}" if line is not None else ""
        available = ", ".join(sorted(connectors)) or "none"
        raise ConfigError(
            f"{_name(path)}{where}: in {config.id!r}, type {config.type!r} is provided "
            f"by no installed package. Available: {available}"
        )

    keys = connectors[config.type] or _NoKeys
    try:
        declared = keys.model_validate(own)
    except ValidationError as error:
        raise _source_error(
            error, entry, index, path, known=_SHARED | set(keys.model_fields)
        ) from error
    return config.model_copy(update={"options": declared.model_dump()})


# Keys that hold a secret rather than name one. Checked by the core before a
# connector's own keys are, because `sources.yaml` is committed to git: a
# connector cannot opt its users into committing credentials, however
# reasonable the key looks in its own documentation (R1.8 row 1).
# Deliberately not `key`: a bare `key` is as likely to be a partition key or a
# sort key as a credential, and refusing it would block configuration nobody
# should have to argue about. These four are not ambiguous.
SECRET_KEYS = frozenset({"token", "password", "secret", "api_key", "apikey"})


def _reject_credentials(entry: dict, index: int, path: Path) -> None:
    """Refuse a source that writes a credential down instead of naming its variable.

    The message names the file, the line and the key, and never the value: an
    error message is read by a person and often pasted into a ticket, which is
    the last place a leaked credential should travel to (R9.8's shape).
    """
    written = sorted(key for key in entry if str(key).casefold() in SECRET_KEYS)
    if not written:
        return

    line = _line_of(path.read_text(encoding="utf-8"), "sources", index, written[0])
    where = f", line {line}" if line is not None else ""
    identifier = entry.get("id")
    owner = f" in {identifier!r}," if identifier else ""
    raise ConfigError(
        f"{_name(path)}{where}:{owner} {written[0]!r} holds a credential, and this "
        f"file is committed to git. Name the variable instead, as "
        f"`{TOKEN_ENV}: JIRA_TOKEN`, and set its value in the environment (R1.8)."
    )


def _source_error(
    error: ValidationError, entry: dict, index: int, path: Path, *, known
) -> ConfigError:
    """A problem with one of a source's keys, named at the line it is -- or should be -- on.

    The same for a shared key and a connector's: which layer checked a key is
    not something the person reading the message needs to know (R3.1).

    An unknown key is almost always a misspelt known one, so the message says
    what was probably meant. A missing key has no line of its own, so the
    message names the line the source starts on.
    """
    text = path.read_text(encoding="utf-8")
    problems = error.errors()
    # A misspelt key shows up twice: as the key it was meant to be, missing, and
    # as itself, unknown. The unknown one is what the person wrote and can fix,
    # so it is named first -- `pth`, with `path` suggested (R3.1 row 1).
    problem = next((p for p in problems if p["type"] == "extra_forbidden"), problems[0])
    key = str(problem["loc"][0]) if problem["loc"] else ""
    if problem["type"] == "extra_forbidden":
        line = _line_of(text, "sources", index, key)
        detail = f"unknown key {key!r}{_suggestion(key, known)}"
    elif problem["type"] == "missing":
        line = _line_of(text, "sources", index)
        detail = f"missing key {key!r}, which its type requires"
    elif key:
        line = _line_of(text, "sources", index, key)
        detail = f"{key!r} -- {problem['msg']}"
    else:
        # A problem between keys rather than with one -- a connector's own
        # validator over the whole entry, as `user_env` without `token_env`
        # (R1.12 row 5). No key to point at, so the source's line is named.
        line = _line_of(text, "sources", index)
        detail = problem["msg"].removeprefix("Value error, ")
    where = f", line {line}" if line is not None else ""
    identifier = entry.get("id")
    owner = f" in {identifier!r}," if identifier else ""
    return ConfigError(f"{_name(path)}{where}:{owner} {detail}")


def _suggestion(key: str, known) -> str:
    """` -- did you mean 'path'?`, or nothing when no known key is close."""
    matches = difflib.get_close_matches(key, sorted(known), n=1)
    return f" -- did you mean {matches[0]!r}?" if matches else ""


def load_pipeline(path: Path, *, providers: Collection[str]) -> PipelineConfig:
    """Load and validate one pipeline, with its schemas.

    Relative paths inside the file are resolved against the pipeline's own
    directory, so a pipeline is self-contained and can be moved.

    `providers` is every model provider an installed package declares. It is
    passed in because this layer may import only the domain, and the registry
    is infrastructure: the CLI reads it from the entry points, and a test
    passes a set (R9.1).
    """
    document = _read_yaml(path)
    document["name"] = path.parent.name

    pipeline = _validate(PipelineConfig, document, path)

    # Before the pinned check: whether an id is pinned depends on its
    # provider's form, and a provider nobody installed has none to check
    # against. Found now rather than at the first cache miss (R9.1).
    provider = provider_of(pipeline.model)
    if provider not in providers:
        line = _line_of(path.read_text(encoding="utf-8"), "model")
        available = ", ".join(sorted(providers)) or "none"
        raise ConfigError(
            f"{_name(path)}, line {line}: model {pipeline.model!r} names provider "
            f"{provider!r}, which no installed package provides. Available: {available}"
        )

    # Whether the model is pinned is the domain's decision (R0.6); which line it
    # was written on is this layer's, because only this layer has the file (R3.4).
    try:
        check_pinned(pipeline.model)
    except ValueError as error:
        line = _line_of(path.read_text(encoding="utf-8"), "model")
        raise ConfigError(f"{_name(path)}, line {line}: {error}") from error

    # The pure checks live in domain and raise ValueError; this layer is what
    # knows which file the value came out of.
    for check in (validate_step_ids, validate_references, validate_modes):
        try:
            check(pipeline)
        except ValueError as error:
            raise ConfigError(f"{_name(path)}: {error}") from error

    _validate_output_declarations(pipeline, path)
    _validate_prompt_placeholders(pipeline, path)
    _validate_gold(pipeline, path)
    _validate_judge_thresholds(pipeline, path)
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


def load_judge_rubrics(path: Path) -> dict[str, str]:
    """The rubric each judged field names in its declaration (R7.14, spec 006).

    `declare_fields` checks that a `free_text` field names a `judge:` and then
    keeps only the kind, because the scorer's field list is what it exists to
    build. A calibration needs the path as well: the rubric's hash travels with
    the figure, since a measurement made against another rubric is not this
    judge's calibration (R7.6).

    The value is returned as written. It is relative to the pipeline's own
    directory, as `prompts/` and `output` are, and resolving it is the caller's
    -- this layer is told which file to read, not where a pipeline lives.
    """
    document = _read_yaml(path)
    declared = document.get("fields") or {}
    return {
        str(name): str(entry["judge"])
        for name, entry in declared.items()
        if isinstance(entry, dict) and entry.get("judge")
    }


def load_output_schema(path: Path) -> OutputSchema:
    """What one declaration contributes to a run (R6.10, R6.11).

    The schema shown to the model is generated from the declaration. The key
    takes the declaration's own text, hashed the way spec 005 hashes every
    configuration file -- so an edit the generated schema cannot see still moves
    the key.
    """
    return OutputSchema(schema=json_schema(load_fields(path)), declaration_hash=text_hash(path))


def load_output_schemas(pipeline: PipelineConfig, path: Path) -> dict[str, OutputSchema]:
    """What each step's declaration contributes to a run, by step id.

    Only the declarations a step's `output` names. A file beside them that no
    step names is in no key (R6.11 row 4), and a step that names none has no
    entry at all (R3.10 row 5). `path` is the pipeline's own `pipeline.yaml`,
    which every `output` is relative to.
    """
    return {
        step.id: load_output_schema(path.parent / step.output)
        for step in pipeline.steps
        if step.output is not None
    }


def _validate_gold(pipeline: PipelineConfig, path: Path) -> None:
    """R3.7 — a declared gold set exists, and every file in it conforms to spec 007.

    Checked here, before anything runs: a gold set that cannot be read is a run
    that cannot be scored, and an unattributed answer in it is an unaudited
    definition of correct (R7.7). A pipeline with no `gold` is fine -- only
    `dossier eval` needs one.

    Resolved against the workspace, not the pipeline's own directory as
    `prompts/` and `output` are: a gold set is a workspace asset that several
    pipelines may share, and `dossier eval --gold` names it the same way. A
    pipeline is always `<workspace>/pipelines/<name>/pipeline.yaml` (spec 003).
    """
    if pipeline.gold is None:
        return
    directory = path.parents[2] / pipeline.gold
    if not directory.is_dir():
        line = _line_of(path.read_text(encoding="utf-8"), "gold")
        where = f", line {line}" if line is not None else ""
        raise ConfigError(
            f"{_name(path)}{where}: gold {pipeline.gold!r} is not a directory ({directory})"
        )
    for gold_file in sorted(directory.glob("*.json")):
        try:
            document = json.loads(gold_file.read_text(encoding="utf-8"))
            GoldDocument.model_validate(document)
        except ValidationError as error:
            raise ConfigError(
                f"{_name(path)}: gold file {gold_file.name}: {_describe(error, {})}"
            ) from error
        except ValueError as error:
            raise ConfigError(
                f"{_name(path)}: gold file {gold_file.name} is not valid JSON -- {error}"
            ) from error


# The human-scored cases a judge is measured against, one file per judged field.
# Under a subdirectory so a sample is not one of the `<document>.json` files a
# gold set is made of, which `_validate_gold` above would otherwise read as a
# verified answer (R7.16, R3.7 row 1).
SAMPLES_DIR = "samples"


def load_calibration_sample(directory: Path, field: str) -> tuple[CalibrationCase, ...]:
    """The human-scored cases a judge is measured on, from the gold set (R7.16).

    `<gold>/samples/<field>.jsonl`, one record per line and in file order: a
    sample is a list a reviewer grows by appending, and the order it was written
    in is the order it reads back in.

    A bad record names its line. A sample runs to hundreds of lines, and
    "somewhere in this file" is not a fix anyone can act on (R3.1's shape).

    Not the gold answers. A gold file says what the right value *is*; a sample
    says whether a *candidate* answer is supported, which is the question a judge
    is asked -- and it has to be able to hold a wrong candidate (R7.12).
    """
    path = directory / SAMPLES_DIR / f"{field}.jsonl"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ConfigError(
            f"{field}: no calibration sample at {path}. A judge cannot be measured "
            "against a sample nobody has written (R7.14, R7.16)."
        ) from error

    cases: list[CalibrationCase] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as error:
            raise ConfigError(
                f"{path.name}, line {number}: not valid JSON -- {error}"
            ) from error
        try:
            cases.append(CalibrationCase.model_validate(record))
        except ValidationError as error:
            raise ConfigError(
                f"{path.name}, line {number}: {_describe(error, record)}"
            ) from error
    return tuple(cases)


# The agreed bar for each judged field, kept with the gold set the judge is
# measured against. YAML rather than JSON so it is not one of the
# `<document>.json` files a gold set is made of, which `_validate_gold` above
# would otherwise try to read as a verified answer (R7.13).
JUDGE_FILE = "judge.yaml"


def load_judge_thresholds(directory: Path) -> dict[str, dict[str, float]]:
    """The agreement each judged field's judge must reach, per state (R7.20).

    With the gold set rather than the field declaration, because a threshold is
    a property of scoring: the declaration is hashed as text into every stage key
    that reads it (R6.11), so a bar raised from 0.95 to 0.96 there would re-run
    every extraction the pipeline has cached, to change a number no extraction
    can affect.

    Keyed by grounding state, because a field answered from text and the same
    field read off a page are two judges asked two questions, and they do not
    measure the same (R6.15, R7.20). A scalar is the `grounded` bar, so a gold
    set written before that was true loads unchanged.
    """
    document = _read_yaml(directory / JUDGE_FILE)

    thresholds: dict[str, dict[str, float]] = {}
    for field, declared in document.items():
        name = str(field)
        if isinstance(declared, dict):
            unknown = sorted(
                str(state) for state in declared if str(state) not in JUDGED_STATES
            )
            if unknown:
                # Named rather than ignored. A bar under a state nothing reads
                # gates nothing and reads exactly like one somebody agreed to.
                raise ConfigError(
                    f"{JUDGE_FILE}: {name!r} declares a threshold for {unknown[0]!r}, "
                    f"which is not a grounding state. The states are "
                    f"{', '.join(JUDGED_STATES)} (R7.20)."
                )
            states = {str(state): value for state, value in declared.items()}
        else:
            states = {GROUNDED: declared}

        thresholds[name] = {
            state: _threshold(value, field=name, state=state) for state, value in states.items()
        }
    return thresholds


def _threshold(value: object, *, field: str, state: str) -> float:
    """One declared figure, checked as R7.13 row 3 checked it.

    The shape moved a level deeper and the checks moved with it. A shape change
    that quietly stopped checking the numbers would be a worse regression than
    the shape was an improvement.
    """
    # `bool` first: it is an `int` in Python, and `root_cause: true` is a
    # mistake worth naming rather than silently reading as 1.0.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(
            f"{JUDGE_FILE}: {field!r} {state} is {value!r}, and an agreement "
            "threshold is a number between 0 and 1"
        )
    if not 0.0 <= value <= 1.0:
        raise ConfigError(
            f"{JUDGE_FILE}: {field!r} {state} is {value!r}; an agreement threshold is a "
            "proportion between 0 and 1. A threshold of 95 rather than 0.95 makes "
            "every judge ineligible forever, and reads like strict configuration "
            "rather than a typo."
        )
    return float(value)


def _validate_judge_thresholds(pipeline: PipelineConfig, path: Path) -> None:
    """R7.20 — every judged field has a bar for every state it can be decided in.

    Only when a gold set is declared: a pipeline with no `gold` is never scored,
    so it has no judge to gate (R3.7 row 4). A judged field with no bar would be
    reported as though it had cleared one, which is the failure R7.5 exists to
    prevent -- and finding that out at scoring time is finding it out after the
    run has been paid for.
    """
    if pipeline.gold is None:
        return

    judged = sorted(
        name
        for step in pipeline.steps
        if step.output is not None
        for name, kind in load_fields(path.parent / step.output).items()
        if kind is FieldKind.FREE_TEXT
    )
    if not judged:
        return

    directory = path.parents[2] / pipeline.gold
    thresholds = load_judge_thresholds(directory)
    missing = [name for name in judged if name not in thresholds]
    if missing:
        raise ConfigError(
            f"{_name(path)}: field {missing[0]!r} is judged against a rubric and has "
            f"no agreement threshold in {directory / JUDGE_FILE}. A judged field with "
            "no bar is reported as though it had cleared one (R7.5, R7.20)."
        )

    # A `per_part` step is the only thing that hands a stage a picture (R3.12),
    # so it is the only thing that can produce a `described` verdict (R6.15).
    # Asked for nowhere else, because a bar every author copies without meaning
    # it is how a threshold stops being agreed.
    if not any(step.mode == "per_part" and step.output is not None for step in pipeline.steps):
        return

    undescribed = [name for name in judged if DESCRIBED not in thresholds[name]]
    if undescribed:
        raise ConfigError(
            f"{_name(path)}: field {undescribed[0]!r} is produced by a per_part step, "
            f"which can answer it from a page image, and {directory / JUDGE_FILE} "
            f"declares no {DESCRIBED!r} threshold for it. A described verdict gated on "
            "a figure measured against text is not gated (R6.15, R7.20)."
        )


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


def _line_of(text: str, *keys: str | int) -> int | None:
    """The 1-based line the last of `keys` is written on, or `None` if it is not there.

    `keys` is a path into the document: a string names a mapping key, an int an
    item in a list -- `("sources", 0, "pth")`. Composed rather than loaded:
    `safe_load` discards where a value came from, and a message that names the
    key without the line leaves a person searching a file for something the
    loader already found (R3.1).
    """
    node = yaml.compose(text)
    line = None
    for key in keys:
        if isinstance(key, int):
            if not isinstance(node, yaml.SequenceNode) or key >= len(node.value):
                return None
            node = node.value[key]
            line = node.start_mark.line + 1
            continue
        if not isinstance(node, yaml.MappingNode):
            return None
        match = next(((name, value) for name, value in node.value if name.value == key), None)
        if match is None:
            return None
        line = match[0].start_mark.line + 1
        node = match[1]
    return line
