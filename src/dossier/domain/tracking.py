"""Tracking decisions (spec 010): whether it is on, and what may be recorded.

Pure. The environment arrives as a mapping that `dossier.config` reads and hands
in -- this layer reads nothing itself -- which is what lets every decision here
be tested with a dict.

Tracking observes a run and is never an input to one (R0.10): nothing decided
here enters a key, a manifest or a score.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from dossier.domain.judges import Calibration

ENABLED = "DOSSIER_MLFLOW_ENABLED"
TRACKING_URI = "DOSSIER_MLFLOW_TRACKING_URI"
EXPERIMENT = "DOSSIER_MLFLOW_EXPERIMENT"
CAPTURE = "DOSSIER_MLFLOW_CAPTURE"
RUN_PREFIX = "DOSSIER_MLFLOW_RUN_PREFIX"
RUN_NAME = "DOSSIER_MLFLOW_RUN_NAME"
RUN_LABEL = "DOSSIER_MLFLOW_RUN_LABEL"
USER = "DOSSIER_MLFLOW_USER"

# What a span may carry: the text a stage read and wrote, or only its hashes.
_CAPTURES = ("full", "hashes")

# One experiment per pipeline and command kind: a sync's fetch counts, a run's
# traces and an eval's per-field accuracy are not comparable with one another,
# so they do not share an experiment unless someone asks them to (spec 010).
DEFAULT_EXPERIMENT = "dossier-audit/{pipeline}/{kind}"

# Exactly spec 010's placeholders. `{gold}` exists only for the two commands that
# read a gold set, `eval` and `calibrate`.
_PLACEHOLDERS = ("pipeline", "kind", "gold")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class TrackingSettings(BaseModel):
    """Where this machine records its runs, when it records them at all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str


def settings(environ: Mapping[str, str]) -> TrackingSettings | None:
    """This machine's tracking settings, or `None` when tracking is off (R10.1).

    `None` rather than a flag: a caller handed nothing to record with cannot
    record. Only `DOSSIER_` variables are read, so MLflow's own
    `MLFLOW_TRACKING_URI`, left in a shell from another project, switches
    nothing on (R10.1 row 5, R9.11).

    An empty switch counts as unset, as an empty endpoint does (R9.2):
    `.env.example` ships its variables blank, and blank is not a decision.
    """
    switch = environ.get(ENABLED, "")
    if switch in ("", "false"):
        return None
    if switch != "true":
        # Refused rather than read as off: a typo that silently disabled
        # tracking would be found only after the run it should have recorded.
        raise ValueError(f"{ENABLED} is {switch!r}; it takes `true` or `false`.")
    uri = environ.get(TRACKING_URI, "")
    if not uri:
        # No default in code, for the reason the project's default model has
        # none: a default is written into `.env.example`, where it can be read.
        raise ValueError(
            f"{ENABLED} is true, and {TRACKING_URI} is not set. Set it to where MLflow "
            "is served on this machine; `.env.example` names http://localhost:5000."
        )
    return TrackingSettings(uri=uri)


def experiment_name(
    *, kind: str, pipeline: str, gold: str | None, environ: Mapping[str, str]
) -> str:
    """The experiment a `dossier <kind>` record lands in (R10.2).

    The command's own template, `DOSSIER_MLFLOW_EXPERIMENT_<KIND>`, wins over the
    shared `DOSSIER_MLFLOW_EXPERIMENT`, which wins over the default. `gold` is
    the gold directory as the command was given it; `{gold}` renders its name,
    so `gold/incidents` gives `incidents`.

    A template naming a placeholder nothing can fill is refused before any work,
    naming the variable it came from: rendered literally, `{source}` would create
    an experiment nobody meant, and records would pile up in it unnoticed.
    """
    own = f"{EXPERIMENT}_{kind.upper()}"
    variable = own if environ.get(own) else EXPERIMENT
    template = environ.get(variable) or DEFAULT_EXPERIMENT

    used = set(_PLACEHOLDER.findall(template))
    unknown = sorted(used - set(_PLACEHOLDERS))
    if unknown:
        allowed = ", ".join(f"{{{name}}}" for name in _PLACEHOLDERS)
        raise ValueError(
            f"{variable} is {template!r}, which uses {{{unknown[0]}}}; a template may "
            f"use only {allowed}."
        )
    if "gold" in used and gold is None:
        # A sync, a convert and a run read no gold set, so there is nothing to
        # put there. The per-kind variables exist to override the shared one.
        raise ValueError(
            f"{variable} is {template!r}, and `dossier {kind}` reads no gold set, so "
            f"there is nothing to put in {{gold}}. Set {own} to a template without it."
        )

    values = {"pipeline": pipeline, "kind": kind, "gold": _gold_name(gold) if gold else ""}
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


# The name each kind of record is given (R10.10). Data rather than an f-string at
# the call site, because a person overrides one of these by name -- and because
# the defaults are a table in spec 010 that a reader can check this against.
DEFAULT_NAMES = {
    "sync": "{prefix}sync {started}{label}",
    "convert": "{prefix}convert {started}{label}",
    # The run id alone, as R11.1 row 1 asserts it. A run directory is named this,
    # and a record named anything else would stop being the thing a person pastes
    # from one to the other.
    "run": "{prefix}{run_id}{label}",
    "eval": "{prefix}eval {run_id} · {model}{label}",
    "compare": "{prefix}compare {a} -> {b}{label}",
    "calibrate": "{prefix}calibrate {gold} · {judge_model}{label}",
}

# What ` · ` separates. A name is read left to right, and the separator belongs to
# the segment that may be absent rather than to the template around it -- which is
# what lets one prefix variable open every kind's name without six templates being
# rewritten, and leaves an unset one with no stray separator to strip (R10.10 row 6).
SEPARATOR = " · "

# The placeholders whose value is a hash, and which therefore render as the eight
# characters every spec displays rather than the 64 a real digest carries (R0.7).
# Decided here rather than at each call site: a caller hands over the hash it
# holds, and six callers truncating for themselves is six chances to differ.
_HASH_PLACEHOLDERS = ("gold_hash", "pipeline_hash")
_DISPLAY_HASH = 8

# What each kind of command holds to put in its own name. Declared rather than
# inferred from what a caller happened to pass, so a template is refused at the
# same point whether or not the value would have been there this once -- as an
# experiment template is (R10.2).
_EVERY_COMMAND = ("prefix", "label", "pipeline", "kind", "started")
NAME_PLACEHOLDERS = {
    "sync": _EVERY_COMMAND,
    "convert": _EVERY_COMMAND,
    "run": (*_EVERY_COMMAND, "run_id", "model", "pipeline_hash"),
    "eval": (*_EVERY_COMMAND, "run_id", "model", "pipeline_hash", "gold", "gold_hash"),
    "compare": (*_EVERY_COMMAND, "a", "b", "gold", "gold_hash"),
    "calibrate": (*_EVERY_COMMAND, "gold", "gold_hash", "judge_model"),
}


# Every tag dossier writes under MLflow's own prefix (R10.12). A closed list, and
# a test asserts it is this one: `mlflow.runName` is the trap, because MLflow
# reads a run's name from that tag as well as from `create_run`'s argument, and
# writing it would give a name two sources when R10.10 gives it one.
MLFLOW_TAGS = (
    "mlflow.user",
    "mlflow.source.name",
    "mlflow.source.type",
    "mlflow.note.content",
)

# Where a shell records the account a command ran under, in the order a machine
# is likely to have them. Read out of the same mapping as everything else, so no
# part of `domain/` asks the operating system anything (R9.11).
_ACCOUNT = ("USERNAME", "USER", "LOGNAME")


def user_for(environ: Mapping[str, str]) -> str:
    """Who a record says ran the command (R10.12).

    `unknown` when nothing names anybody, which is exactly what
    `MlflowClient.create_run` stores when no `mlflow.user` tag reaches it: this
    path is no worse than the one before the rule, and it is a value rather than
    an absence, so the column reads the same on every record.
    """
    named = environ.get(USER, "")
    if named:
        return named
    for variable in _ACCOUNT:
        found = environ.get(variable, "")
        if found:
            return found
    return "unknown"


def label_for(given: str | None, environ: Mapping[str, str]) -> str:
    """The label this record carries: what was typed, else what was set (R10.11).

    An argument wins over a variable, as it does everywhere else in this tool: a
    variable that could not be overridden per command would let
    `DOSSIER_MLFLOW_RUN_LABEL=nightly` left in a shell silently relabel a run
    someone made by hand.

    Empty rather than `None` for "no label", because both the name and the tag
    read it and two callers each handling a `None` is two chances to differ.
    """
    return given or environ.get(RUN_LABEL, "")


def name_template(*, kind: str, environ: Mapping[str, str]) -> str:
    """The template a `dossier <kind>` record is named from, checked (R10.10).

    Separate from the rendering because the two happen at different moments. A
    command resolves its template at startup, where a bad one is refused before
    any work (R10.5's moment); it renders the name later, when it holds the run
    id or the figures the name carries. Resolving twice is cheaper than carrying
    a resolved template through five signatures, and both calls are pure.
    """
    variable = f"{RUN_NAME}_{kind.upper()}"
    template = environ.get(variable) or DEFAULT_NAMES[kind]

    available = NAME_PLACEHOLDERS[kind]
    unknown = sorted(set(_PLACEHOLDER.findall(template)) - set(available))
    if unknown:
        # Named rather than rendered literally or left blank: a run called
        # `{gold} 20260806T142203Z-4f1a` is a name nobody meant, and records pile
        # up under it unnoticed (R10.10 row 4).
        allowed = ", ".join(f"{{{name}}}" for name in available)
        raise ValueError(
            f"{variable} is {template!r}, which uses {{{unknown[0]}}}; "
            f"`dossier {kind}` may use {allowed}."
        )
    return template


def run_name(*, kind: str, values: Mapping[str, str], environ: Mapping[str, str]) -> str:
    """The name a `dossier <kind>` record is given, rendered from its template (R10.10).

    The experiment says which records are comparable (R10.2); the name says which
    one this is. Every placeholder is a value the command already holds -- the run
    it reproduced, the model that run pinned -- so a name restates and never
    computes, as every other record does (spec 011).
    """
    template = name_template(kind=kind, environ=environ)
    prefix = environ.get(RUN_PREFIX, "")
    rendered = {
        name: value[:_DISPLAY_HASH] if name in _HASH_PLACEHOLDERS else value
        for name, value in values.items()
    }
    rendered["prefix"] = f"{prefix}{SEPARATOR}" if prefix else ""
    label = values.get("label", "")
    rendered["label"] = f"{SEPARATOR}{label}" if label else ""
    rendered["kind"] = kind
    return _PLACEHOLDER.sub(lambda match: rendered[match.group(1)], template)


def tags(
    *,
    kind: str,
    pipeline: str,
    label: str = "",
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The tags every record carries, whichever experiment it lands in (R10.3).

    They keep a shared experiment filterable: with every command recording to
    one `dossier-audit`, a run and an eval are told apart by `dossier.kind`, and
    two pipelines by `dossier.pipeline`. Written only under dossier's own prefix:
    what MLflow records about a run -- `mlflow.user`, `mlflow.source.name` -- is
    left as MLflow sets it.
    """
    written = {"dossier.kind": kind, "dossier.pipeline": pipeline}
    if label:
        # Absent when nobody labelled it, rather than present and empty: a label
        # is supplied or it is not, so absent reads correctly. `dossier.regressed`
        # goes the other way (R11.9 row 3) because a comparison computes it every
        # time, and there an absent tag would read as a record written before the
        # rule existed (R10.11 row 4).
        written["dossier.label"] = label

    # Three of the four `mlflow.*` tags R10.12 permits. The fourth,
    # `mlflow.note.content`, is written when a run closes and its figures exist
    # (R11.12), so it is not here.
    #
    # Written rather than left to MLflow, because MLflow does not write them on
    # this path: `MlflowClient.create_run` reads `mlflow.user` out of the tags
    # handed to it and defaults it to `unknown`, and sets no source at all. R10.3
    # said they were "left as MLflow sets them"; they were left empty.
    written["mlflow.user"] = user_for(environ or {})
    written["mlflow.source.name"] = f"dossier {kind}"
    # `LOCAL` is MLflow's own vocabulary for "a command someone ran", as against
    # NOTEBOOK, JOB or PROJECT. A `dossier` command is always the first.
    written["mlflow.source.type"] = "LOCAL"
    return written


# The per-source counts each command prints, in the order it prints them (R2.13,
# R8.8). Recorded under the same names, so MLflow and the terminal cannot tell
# two different stories (spec 011).
_COUNTS = {
    "sync": ("known", "changed", "new", "fetched", "failed"),
    "convert": ("held", "converted", "cached", "failed"),
}


def count_metrics(*, kind: str, source: str, counts: Mapping[str, int]) -> dict[str, int]:
    """The metrics a `dossier sync` or `dossier convert` records for one source (R11.4).

    Named `<source>/<count>`, so MLflow's UI groups every count of one source
    under its id. Every count is required and every one is recorded, zeros
    included: a source with nothing to report is still listed, because a
    missing source is indistinguishable from a skipped one (R2.13).
    """
    names = _COUNTS.get(kind)
    if names is None:
        raise ValueError(
            f"`dossier {kind}` records no per-source counts; only "
            f"{' and '.join(f'`dossier {name}`' for name in _COUNTS)} do."
        )
    missing = [name for name in names if name not in counts]
    if missing:
        raise ValueError(
            f"{source}: no {', '.join(missing)} count to record. Every count is recorded, "
            "zeros included -- a missing one reads as a source that was skipped (R2.13)."
        )
    return {f"{source}/{name}": counts[name] for name in names}


def calibration_record(
    *, field: str, calibration: Calibration
) -> tuple[dict[str, str], dict[str, float]]:
    """The params and metrics a `dossier calibrate` records for one judged field (R11.5).

    The figures are the ones R7.14 writes to the calibration file and the
    terminal prints, so the file, the terminal and MLflow cannot disagree. What
    the figure was measured against -- the judge and the rubric -- are params;
    the agreement and the case count are metrics, so two measurements under two
    judges sit side by side in MLflow's comparison. The agreement is recorded as
    the percentage the terminal prints, as accuracy is (spec 011).
    """
    # Rounded to the one decimal the terminal prints (`.1%`): 0.57 * 100 is
    # 56.99999999999999 in floating point, and a record that differed from the
    # printed line in its last digits is exactly the disagreement spec 011
    # exists to rule out.
    percentage = round(calibration.agreement * 100, 1)
    return (
        {
            f"judge/{field}/model": calibration.judge_model,
            f"judge/{field}/rubric": calibration.rubric_hash,
        },
        {
            f"judge/{field}/agreement": percentage,
            f"judge/{field}/cases": calibration.sample_size,
        },
    )


def case_tags(*, document: str, verified: bool, judged: bool) -> dict[str, str]:
    """The tags one calibration trace carries: its document and both verdicts (R11.5).

    Both verdicts, as words rather than booleans, so the cases where the judge
    and the reviewer disagree are a filter on two tags in MLflow's UI rather
    than a re-run. The file R7.14 writes holds the agreement figure and not the
    cases behind it, so this is the only place a disagreement is kept.
    """
    return {
        "dossier.document": document,
        "dossier.verified": _verdict(verified),
        "dossier.judged": _verdict(judged),
    }


def _verdict(supported: bool) -> str:
    return "supported" if supported else "unsupported"


def capture(environ: Mapping[str, str]) -> str:
    """What a span may carry on this machine: `full` text, or only `hashes` (R10.8).

    `full` unless set -- an empty value counts as unset, as `.env.example` ships
    it blank. Any other value is refused before any work: read as `full` it would
    copy text the person meant to keep out of the server, and read as `hashes` it
    would be a guess.
    """
    value = environ.get(CAPTURE, "") or "full"
    if value not in _CAPTURES:
        raise ValueError(f"{CAPTURE} is {value!r}; it takes `full` or `hashes`.")
    return value


def span_payload(
    *,
    capture: str,
    identity: Mapping[str, object],
    prompt: str,
    reply: str,
    hashes: Mapping[str, object],
) -> dict[str, object]:
    """What one stage span holds, as the capture setting allows (R10.8).

    `identity` -- the step, document key, model identifier, attempt count, field
    names and verdicts -- is recorded under both settings: it says which work
    the span was and discloses nothing. `full` adds the rendered prompt and the
    model's reply. `hashes` adds the prompt, input and key hashes instead, which
    say exactly what was asked without holding a word of it: anyone who has the
    documents can check them, and nobody who has only the server can read them.
    """
    payload: dict[str, object] = dict(identity)
    if capture == "full":
        payload.update(prompt=prompt, reply=reply)
    elif capture == "hashes":
        payload.update(
            prompt_hash=hashes["prompt"],
            input_hashes=list(hashes["inputs"]),
            key=hashes["key"],
        )
    else:
        raise ValueError(f"capture is {capture!r}; it is `full` or `hashes`.")
    return payload


def _gold_name(gold: str) -> str:
    """`incidents` from `gold/incidents` or `gold/incidents/`: the set's own name."""
    return gold.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
