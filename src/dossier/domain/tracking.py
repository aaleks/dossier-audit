"""Tracking decisions (spec 010): whether it is on, and what may be recorded.

Pure. The environment arrives as a mapping that `dossier.config` reads and hands
in -- this layer reads nothing itself -- which is what lets every decision here
be tested with a dict.

Tracking observes a run and is never an input to one (R0.10): nothing decided
here enters a key, a manifest or a score.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dossier.domain.grounding import FieldVerdict
from dossier.domain.hashing import content_hash
from dossier.domain.judges import Calibration
from dossier.domain.resolution import ResolvedPlan
from dossier.domain.scoring import (
    Failure,
    FieldDelta,
    FieldTotal,
    overall,
    regressed_fields,
    weakest,
)
from dossier.domain.usage import Tokens

ENABLED = "DOSSIER_MLFLOW_ENABLED"
TRACKING_URI = "DOSSIER_MLFLOW_TRACKING_URI"
EXPERIMENT = "DOSSIER_MLFLOW_EXPERIMENT"
CAPTURE = "DOSSIER_MLFLOW_CAPTURE"
RUN_PREFIX = "DOSSIER_MLFLOW_RUN_PREFIX"
RUN_NAME = "DOSSIER_MLFLOW_RUN_NAME"
RUN_LABEL = "DOSSIER_MLFLOW_RUN_LABEL"
USER = "DOSSIER_MLFLOW_USER"
# The per-machine namespace in front of every name dossier publishes into
# MLflow's global namespace -- a prompt's and a dataset's (R10.13).
NAMESPACE = "DOSSIER_MLFLOW_NAMESPACE"
# The variable NAMESPACE replaced, which namespaced prompts alone (R14.8). Named
# so it can be refused by name rather than ignored (R10.15).
RETIRED_PROMPT_PREFIX = "DOSSIER_MLFLOW_PROMPT_PREFIX"

AUTH = "DOSSIER_MLFLOW_AUTH"
AUTH_USERNAME = "DOSSIER_MLFLOW_AUTH_USERNAME"
AUTH_PASSWORD = "DOSSIER_MLFLOW_AUTH_PASSWORD"
AUTH_TOKEN = "DOSSIER_MLFLOW_AUTH_TOKEN"
OIDC_TOKEN_URL = "DOSSIER_MLFLOW_OIDC_TOKEN_URL"
OIDC_CLIENT_ID = "DOSSIER_MLFLOW_OIDC_CLIENT_ID"
OIDC_CLIENT_SECRET = "DOSSIER_MLFLOW_OIDC_CLIENT_SECRET"
OIDC_SCOPE = "DOSSIER_MLFLOW_OIDC_SCOPE"
OIDC_AUDIENCE = "DOSSIER_MLFLOW_OIDC_AUDIENCE"
OIDC_REFRESH_SECONDS = "DOSSIER_MLFLOW_OIDC_REFRESH_SECONDS"
CA_BUNDLE = "DOSSIER_MLFLOW_CA_BUNDLE"

# How close to its expiry an access token is fetched again (R10.19): thirty
# seconds, agreed 2026-09-23, and set per machine by the variable above.
DEFAULT_REFRESH_SECONDS = 30

# The ways dossier can authenticate to MLflow (R10.16), and what each one needs.
# Chosen by name rather than inferred from which variables are set: a guess that
# picked the wrong mode would be found only after the run it should have recorded.
_AUTH_MODES = ("none", "basic", "bearer", "oidc")
_AUTH_NEEDS: dict[str, tuple[tuple[str, str], ...]] = {
    "none": (),
    "basic": (("username", AUTH_USERNAME), ("password", AUTH_PASSWORD)),
    "bearer": (("token", AUTH_TOKEN),),
    "oidc": (
        ("token_url", OIDC_TOKEN_URL),
        ("client_id", OIDC_CLIENT_ID),
        ("client_secret", OIDC_CLIENT_SECRET),
    ),
}

# What a span may carry: the text a stage read and wrote, or only its hashes.
_CAPTURES = ("full", "hashes")

# One experiment per pipeline and command kind: a sync's fetch counts, a run's
# traces and an eval's per-field accuracy are not comparable with one another,
# so they do not share an experiment unless someone asks them to (spec 010).
DEFAULT_EXPERIMENT = "dossier-audit/{pipeline}/{kind}"
# The default for a command that belongs to no pipeline, `dossier gc`: the
# pipeline segment dropped rather than rendered empty (R11.28).
DEFAULT_EXPERIMENT_WITHOUT_PIPELINE = "dossier-audit/{kind}"

# Exactly spec 010's placeholders. `{gold}` exists only for the two commands that
# read a gold set, `eval` and `calibrate`.
_PLACEHOLDERS = ("pipeline", "kind", "gold")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class MlflowAuth(BaseModel):
    """How this machine authenticates to its MLflow server (R10.16).

    Every secret is kept out of `repr`, as `Credential.value` and
    `Endpoint.api_key` are (R9.8): a settings object printed into a refusal or
    a log line discloses nothing (R10.7).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["none", "basic", "bearer", "oidc"] = "none"
    username: str | None = None
    password: str | None = Field(default=None, repr=False)
    token: str | None = Field(default=None, repr=False)
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = Field(default=None, repr=False)
    scope: str | None = None
    audience: str | None = None
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS


class TrackingSettings(BaseModel):
    """Where this machine records its runs, when it records them at all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    uri: str
    auth: MlflowAuth = MlflowAuth()
    # A PEM-encoded CA certificate every connection to MLflow and its identity
    # provider is verified against, or `None` for the system's store (R10.20).
    # The path as given; the adapter resolves it against the working directory.
    ca_bundle: str | None = None


def namespaced(name: str, namespace: str) -> str:
    """R10.13 — `name` with this machine's namespace in front of it, or `name` itself.

    One function for a prompt's name and a dataset's, because both are global on
    a server and unique within one workspace and no further: two checkouts
    sharing a server would otherwise publish into one history. Two ways of
    namespacing them would be two ways for the pair to disagree about what a
    machine published.

    Empty is nothing, so a person who never sets the variable sees every name
    exactly as it was composed before the namespace existed -- which is what
    lets a prompt or a dataset published before it be found and not sent again.
    """
    return f"{namespace}.{name}" if namespace else name


# What MLflow refuses in a prompt name (R14.1). A namespace goes in front of every
# prompt name, so it may hold neither -- although a dataset name would take both
# (R10.14: a live spike created and found `team/a.incidents`).
_REJECTED_IN_A_PROMPT_NAME = ("/", ":")


def check_namespace(namespace: str) -> None:
    """R10.14 — refuse a namespace MLflow would reject, naming the variable to change.

    On its own rather than only inside the names it goes into, because a name is
    composed only once a command is already at work: `eval` and `calibrate`
    reached it with their MLflow run open and raised a traceback (R14.10). Checked
    here, it is refused with the rest of the tracking settings, before anything
    is fetched, asked or recorded.

    One namespace goes in front of every published name, so the name it cannot go
    in front of decides -- and a `dataset publish` refuses it as a prompt publish
    does.
    """
    for character in _REJECTED_IN_A_PROMPT_NAME:
        if character in namespace:
            # The variable is named as well as the character: the person reading
            # this never typed the namespace into the command, so the message has
            # to say which setting to go and change.
            raise ValueError(
                f"{NAMESPACE}={namespace!r} cannot be used: MLflow rejects "
                f"{character!r} in a prompt name, and the namespace goes in front of "
                "every one. Choose a namespace holding neither '/' nor ':'."
            )


def namespace(environ: Mapping[str, str]) -> str:
    """This machine's namespace (R10.13), checked (R10.14), its predecessor refused (R10.15).

    The one reader of the namespace, so every command that publishes or looks up
    a name reads it the same way. The retired variable is refused rather than
    ignored: a machine that still sets it would otherwise stop being namespaced
    without a word, and publish into the history it was set to keep apart from.
    Blank is not a decision, as a blank switch is not (R10.1).
    """
    retired = environ.get(RETIRED_PROMPT_PREFIX, "")
    if retired:
        raise ValueError(
            f"{RETIRED_PROMPT_PREFIX} is retired: set {NAMESPACE}={retired} instead. "
            "One namespace now goes in front of every name dossier publishes -- a "
            "dataset's as well as a prompt's -- and the old variable is no longer read."
        )
    value = environ.get(NAMESPACE, "")
    check_namespace(value)
    return value


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
    return TrackingSettings(
        uri=uri, auth=_auth(environ), ca_bundle=environ.get(CA_BUNDLE) or None
    )


def authorization(auth: MlflowAuth) -> str | None:
    """The `Authorization` value a request to MLflow carries, or `None` for no header (R10.17).

    One function, read by the startup check and by the provider MLflow asks on
    every request, so the header checked is the header sent. `oidc` carries a
    token exchanged at run time, which is not a decision this layer can take
    from settings alone (R10.19).
    """
    if auth.mode == "basic":
        pair = f"{auth.username}:{auth.password}".encode()
        return "Basic " + base64.b64encode(pair).decode("ascii")
    if auth.mode == "bearer":
        return f"Bearer {auth.token}"
    if auth.mode == "oidc":
        raise ValueError("an `oidc` header carries an exchanged access token (R10.19)")
    return None


def refused_credential(auth: MlflowAuth) -> str:
    """What a server's refusal says about the credential, naming its variables (R10.18).

    Variables, never values (R10.7). With no mode chosen, the thing to fix is
    that none was: a server asking for a credential was sent none.
    """
    if auth.mode == "none":
        return (
            f"it wants a credential, and {AUTH} is not set. Set it to `basic`, `bearer` "
            "or `oidc`, with that mode's variables"
        )
    named = " and ".join(
        variable for _, variable in _AUTH_NEEDS[auth.mode] if variable != OIDC_TOKEN_URL
    )
    return f"it did not accept the `{auth.mode}` credential in {named}"


# The two answers that are a refusal rather than a server going away (R10.22).
_REFUSALS = {401: "Unauthorized", 403: "Forbidden"}


def refused_record(auth: MlflowAuth, *, status: int, experiment: str) -> str:
    """What the first record a server refuses says (R10.22): the status, and what to fix.

    A 403 is a credential the server accepted and will not let write; it names
    who, by variable, and where. A 401 is a credential it did not accept --
    a password changed while a run was at work -- and says so as the startup
    check would (R10.18). Variables, never values (R10.7).
    """
    if status == 403:
        who = {
            "none": f"an anonymous client ({AUTH} is not set)",
            "basic": f"the account in {AUTH_USERNAME}",
            "bearer": f"the token in {AUTH_TOKEN}",
            "oidc": f"the client in {OIDC_CLIENT_ID}",
        }[auth.mode]
        detail = f"{who} may not write to {experiment}"
    else:
        detail = refused_credential(auth)
    return (
        f"MLflow refused a record ({status} {_REFUSALS.get(status, '')}): {detail}. The "
        "command goes on, and every record it could not make is counted at the end"
    )


def _auth(environ: Mapping[str, str]) -> MlflowAuth:
    """The credential `DOSSIER_MLFLOW_AUTH` names, from that mode's variables alone (R10.16).

    A variable belonging to a mode nobody chose is not read: a token left in
    `.env` from last week's setup chooses nothing. `DOSSIER_MLFLOW_USER` is who a
    record says ran it (R10.12) and is never read as a login.

    A refusal names the variable, never a value: an empty one counts as unset,
    as an empty endpoint does (R9.2), because `.env.example` ships them blank.
    """
    mode = environ.get(AUTH, "") or "none"
    if mode not in _AUTH_MODES:
        allowed = ", ".join(f"`{name}`" for name in _AUTH_MODES)
        raise ValueError(f"{AUTH} is {mode!r}; it takes {allowed}.")

    values: dict[str, str] = {}
    for field, variable in _AUTH_NEEDS[mode]:
        value = environ.get(variable, "")
        if not value:
            raise ValueError(f"{AUTH} is `{mode}`, and {variable} is not set.")
        values[field] = value
    if mode == "oidc":
        # Sent with the exchange only when set: Entra ID wants a scope, Auth0 an
        # audience, and Keycloak neither (R10.19 row 5).
        for field, variable in (("scope", OIDC_SCOPE), ("audience", OIDC_AUDIENCE)):
            if environ.get(variable):
                values[field] = environ[variable]
        margin = environ.get(OIDC_REFRESH_SECONDS, "")
        if margin:
            # A whole number of seconds, zero or more. `-5` and `soon` are refused
            # rather than read as the default: a margin someone meant to set and
            # did not is found only when a long run starts losing records.
            if not margin.isdigit():
                raise ValueError(
                    f"{OIDC_REFRESH_SECONDS} is {margin!r}; it takes a whole number of "
                    f"seconds, and is {DEFAULT_REFRESH_SECONDS} when unset."
                )
            values["refresh_seconds"] = int(margin)
    return MlflowAuth(mode=mode, **values)


def token_expiry(*, issued_at: datetime, expires_in: int | None) -> datetime | None:
    """When a token issued at `issued_at` stops being accepted, or `None` if nobody said."""
    return None if expires_in is None else issued_at + timedelta(seconds=expires_in)


def token_due(*, expires_at: datetime | None, now: datetime, margin_seconds: int) -> bool:
    """Whether the token in hand is fetched again before this request (R10.19).

    Due once *no more than* the margin remains: exactly thirty seconds left is
    due, because a request carrying a token with thirty seconds to live may take
    longer than that to arrive. A token whose lifetime nobody stated is always
    due -- fetched per request rather than reused on a guess. A margin longer
    than a token lives makes every request fetch one, which costs a token
    request and never a record.
    """
    if expires_at is None:
        return True
    return (expires_at - now).total_seconds() <= margin_seconds


def experiment_name(
    *, kind: str, pipeline: str | None, gold: str | None, environ: Mapping[str, str]
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
    default = DEFAULT_EXPERIMENT_WITHOUT_PIPELINE if pipeline is None else DEFAULT_EXPERIMENT
    template = environ.get(variable) or default

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

    if "pipeline" in used and pipeline is None:
        # `dossier gc` belongs to no pipeline: rendered empty, `{pipeline}` would
        # file its record under an experiment named for nothing (R11.28).
        raise ValueError(
            f"{variable} is {template!r}, and `dossier {kind}` belongs to no pipeline, so "
            f"there is nothing to put in {{pipeline}}. Set {own} to a template without it."
        )

    values = {
        "pipeline": pipeline or "",
        "kind": kind,
        "gold": _gold_name(gold) if gold else "",
    }
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
    # No pipeline to name it by: `gc` reclaims space across every one (R11.28).
    "gc": "{prefix}gc {started}{label}",
    # Named by its index, which says what was written, and when (R11.33).
    "embed": "{prefix}embed {index} {started}{label}",
    # A search's trace, which belongs to no run (R11.34).
    "search": "{prefix}search {index}{label}",
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
    "gc": ("prefix", "label", "kind", "started"),
    "embed": (*_EVERY_COMMAND, "index"),
    "search": (*_EVERY_COMMAND, "index"),
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


# What a try's record carries beside the tags every record does (R4.24): the
# documents `dossier run --doc` named, so tries are one filter away from runs.
TRY = "dossier.try"


def try_tags(tried: Sequence[str] | None) -> dict[str, str]:
    """The tag that marks a record a try, or none for a full run (R4.24).

    Sorted, and each document once: one set of documents is one tag value,
    whatever order it was typed in. Absent from a full run rather than present
    and empty, as `dossier.label` is when nobody gave one (R10.11).
    """
    if tried is None:
        return {}
    return {TRY: ", ".join(sorted(set(tried)))}


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
# two different stories (spec 011). `returned` and `left_out` are recorded at
# zero although the terminal prints each only when there is one: a missing
# count reads as one never measured (R11.25, R11.26).
_COUNTS = {
    "sync": ("known", "changed", "new", "returned", "fetched", "failed"),
    "convert": ("held", "converted", "cached", "failed", "left_out"),
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


def version_params(plan: ResolvedPlan, *, prefix: str = "") -> dict[str, str]:
    """The version of everything a run used, for the eval that scores it (R11.11).

    Read off the plan the run wrote and never recomputed. A converter pinned at
    `1.3.0` in a manifest is recorded as `1.3.0` on a machine where `1.4.0` is
    installed, because the record describes the run and not the machine that
    scored it (R4.9) -- and because two evals of one run on two laptops that
    disagreed would be worse than no record at all.

    `prefix` is `a/` or `b/` for a comparison, as `a/model` and `b/model` already
    are (R7.8): one set of params would be a claim about both runs that is false
    in exactly the case the change gate exists for.

    A step with no schema records none rather than an empty one: `schema/verify=`
    reads as a schema that was computed and came out empty, which is a different
    and more alarming claim than a step that declares no output.
    """
    recorded = {f"{prefix}pipeline_hash": plan.pipeline_hash}
    for step in plan.steps:
        recorded[f"{prefix}prompt/{step.id}"] = step.prompt_hash
        if step.schema_hash:
            recorded[f"{prefix}schema/{step.id}"] = step.schema_hash
        if step.generated_schema_hash:
            recorded[f"{prefix}generated_schema/{step.id}"] = step.generated_schema_hash
        # A step asked with its own model rather than the pipeline's (R11.22).
        # Nothing for one asked with the pipeline's, which `model` already names:
        # a pipeline whose steps name none records what it recorded before, and
        # keeps its version hash (R13.1).
        if step.model:
            recorded[f"{prefix}model/{step.id}"] = step.model
    # Sorted, though nothing here enters a key (R10.4): an unsorted list would
    # make two evals of one run differ in MLflow for a reason nobody could
    # explain, which is its own kind of wrong (R0.4).
    recorded[f"{prefix}converters"] = ", ".join(
        sorted(f"{converter.id} {converter.version}" for converter in plan.converters)
    )
    recorded[f"{prefix}documents"] = str(len(plan.documents))
    return recorded


def eval_description(
    *,
    run_id: str,
    pipeline: str,
    model: str,
    pipeline_hash: str,
    gold: str,
    gold_hash: str,
    documents: int,
    totals: Sequence[FieldTotal],
    withheld: Mapping[str, str],
    left_out: int = 0,
) -> str:
    """What an eval says about itself, in MLflow's Description (R11.12).

    Generated, never authored. Every line restates one the command printed, and
    every figure is computed from the totals the report was built from -- a
    figure that existed only here would be a second way of arriving at one,
    which is what spec 011 forbids.

    Written when the run closes rather than when it opens, because none of the
    figures exist until the scoring is done.
    """
    lines = [
        f"eval of {run_id} · {pipeline}",
        f"model {model} · pipeline {pipeline_hash[:_DISPLAY_HASH]}",
        # How many of them were scored: `4 documents` over a run that failed one
        # read as all four scored (R11.31, R7.52).
        _gold_line(gold, gold_hash, documents=documents, left_out=left_out),
    ]
    summed = overall(totals)
    if summed is not None:
        # The overall and the breadth it covers, as R7.2 prints them together: a
        # percentage without the field count says nothing about what was measured.
        headline = f"overall {summed.percentage:.1f}% over {len(totals)} fields"
        lowest = weakest(totals)
        if lowest:
            worst = next(total for total in totals if total.field in lowest)
            headline += f" · weakest {worst.field} {worst.percentage:.1f}%"
        lines.append(headline)
    for field, why in withheld.items():
        # Named with the reason and no figure, as the report's line is (R7.15). A
        # field silently dropped would read as one nobody verified, which is a
        # different problem wanting different work (R7.3 row 4).
        lines.append(f"withheld {field} — {why}")
    return "\n".join(lines)


def _gold_line(gold: str, gold_hash: str, *, documents: int, left_out: int) -> str:
    """`gold incidents 3b7e1d90 · 3 of 4 documents`; `· 4 documents` when none was left out."""
    scored = f"{documents - left_out} of " if left_out else ""
    return f"gold {gold} {gold_hash[:_DISPLAY_HASH]} · {scored}{documents} documents"


def comparison_description(
    *,
    runs: tuple[str, str],
    pipeline: str,
    models: tuple[str, str],
    gold: str,
    gold_hash: str,
    documents: int,
    rows: Sequence[FieldDelta],
    overalls: tuple[FieldTotal | None, FieldTotal | None],
    left_out: int = 0,
    failed: tuple[Sequence[Failure], Sequence[Failure]] = ((), ()),
) -> str:
    """What a comparison says about itself (R11.12 row 3).

    The two runs, the model each pinned, the overall's movement and what
    regressed -- the four things the report's own opening line and its markers
    say. `regressed nothing` is said rather than omitted, for the reason R11.9
    row 3 gives for the tag: a missing line reads as a record written before the
    line existed.

    What regressed is every marker the terminal printed: the fields, then each
    document the change lost, beneath them as the terminal lists them (R11.30).
    It said `regressed nothing` beside `INC-4822 … <- regression` before.
    """
    lines = [
        f"compare {runs[0]} -> {runs[1]} · {pipeline}",
        f"model {models[0]} -> {models[1]}",
        # How many of them were compared, as the headline counts them: a
        # document either run left unscored is scored in neither (R11.27, R7.54).
        _gold_line(gold, gold_hash, documents=documents, left_out=left_out),
    ]
    earlier, later = overalls
    if earlier is not None and later is not None:
        moved = later.percentage - earlier.percentage
        lines.append(
            f"overall {earlier.percentage:.1f}% -> {later.percentage:.1f}% ({moved:+.1f})"
        )
    worse = [
        *regressed_fields(rows),
        *(f"{document} (failed at {step})" for step, document, _ in lost_documents(failed)),
    ]
    lines.append(f"regressed {', '.join(worse)}" if worse else "regressed nothing")
    return "\n".join(lines)


def failure_line(*, step: str, document: str, reason: str | None) -> str:
    """The line `dossier run` reports a failed document with, reason and all (R6.31).

    `extract failed on INC-4822` said which document and never why, and with
    MLflow off the reason was printed nowhere. One line, as a stopped command's
    is (R9.20): a reason spanning lines is put on one.
    """
    said = "" if not reason else ": " + " ".join(reason.split())
    return f"{step} failed on {document}{said}"


def not_scored_line(*, step: str, document: str, reason: str | None) -> str:
    """The line `dossier eval` names a document the run failed with (R7.52).

    The document first, where `run`'s line puts the step: `eval` reports
    documents, and this one it counted and did not score (R7.50 row 6). The
    reason on one line, as `run` gives it (R6.31).
    """
    said = "" if not reason else ": " + " ".join(reason.split())
    return f"not scored: {document} failed at {step}{said}"


def not_compared_line(
    *, step: str, document: str, run: str, reason: str | None, regressed: bool
) -> str:
    """The line `--compare` names a document it left out with (R7.55).

    `not_scored_line`'s words, with the run that failed it: a comparison reads
    two runs, and either can have failed the document.
    """
    said = "" if not reason else ": " + " ".join(reason.split())
    marked = "   <- regression" if regressed else ""
    return f"not compared: {document} failed at {step} in {run}{said}{marked}"


def lost_documents(failed: tuple[Sequence[Failure], Sequence[Failure]]) -> list[Failure]:
    """The documents a comparison's change lost: `b` failed them, `a` answered them.

    `failed` is what each run left unscored (R7.53), and the loss is `b`'s
    failure, in the order `b` names them. Not the other way round, where the
    change recovered the document, and not when both failed it, where the change
    lost nothing (R7.55). The one decision behind the terminal's marker, the
    description's `regressed` line (R11.30) and `dossier.lost` (R11.29), so the
    three cannot disagree.
    """
    failed_before = {document for _, document, _ in failed[0]}
    return [failure for failure in failed[1] if failure[1] not in failed_before]


def not_compared_lines(
    failed: tuple[Sequence[Failure], Sequence[Failure]], *, runs: tuple[str, str]
) -> list[str]:
    """Each document a comparison left out, run `a`'s first (R7.55, R7.54).

    `failed` is what each run left unscored (R7.53). A document the change lost
    is marked as a regression, as R7.8 flags every regression.
    """
    lost = {document for _, document, _ in lost_documents(failed)}
    return [
        not_compared_line(
            step=step,
            document=document,
            run=run,
            reason=reason,
            regressed=bool(later) and document in lost,
        )
        for later, (run, failures) in enumerate(zip(runs, failed, strict=True))
        for step, document, reason in failures
    ]


def step_line(
    *,
    step: str,
    documents: int,
    cached: int,
    failed: int,
    described: int = 0,
    findings: int = 0,
    tokens: Tokens | None = None,
    unit: str = "document",
    skipped: str | None = None,
) -> str:
    """The line `dossier run` prints for one step (R6.9, R6.15, R6.16, R5.12).

    Composed here rather than in `cli/` because two readers need exactly these
    words: the terminal, and the description of the record the run closes
    (R11.17). Two format strings would drift, and the drift would look like the
    disagreement spec 011 exists to rule out.

    `described` and `findings` are absent when zero. A `· 0 described` on every
    line of every run of every text pipeline is noise, and the number is
    interesting precisely because it is usually absent (R6.15).

    `tokens` is what the step's model calls cost in this run, last on the line
    because it is what the rest of it cost (R5.12). `None` is a step that asked
    no model, and says nothing -- it would otherwise be on every line of every
    cached run. A side the provider did not report reads `tokens not reported`,
    never `0`. The `,` separator is Python's own and is not locale-aware, so two
    machines print the same line (R0.4).

    `unit` is what the step asked about once each. A `per_group` step's is the
    group: four files that are two contracts are two calls, and `4 document(s)`
    would count what was read rather than what was asked (R3.15 row 1).

    `skipped` is why a step was not asked at all, and is then the whole line:
    `0 document(s)` would read as a step with nothing to do (R4.23).
    """
    if skipped is not None:
        return f"{step}: skipped {skipped}"
    shown = f" · {described} described" if described else ""
    found = f" · {findings} finding(s)" if findings else ""
    return (
        f"{step}: {documents} {unit}(s) · {cached} from cache · {failed} failed{shown}{found}"
        + _spent(tokens)
    )


# MLflow's own attribute for what one LLM call cost, rather than a `dossier.` one:
# MLflow 3 adds every span's into its trace's `mlflow.trace.tokenUsage`, so the
# trace list shows what each (step, document) cost with nothing summed twice
# (R11.20). A name, not an import -- `domain` imports no MLflow.
TOKEN_USAGE = "mlflow.chat.tokenUsage"


def token_usage(tokens: Tokens) -> dict[str, int] | None:
    """One call's count, as `mlflow.chat.tokenUsage` holds it; `None` if unreported.

    A count is not content, so it is recorded under every capture setting
    (R10.8). A side the provider did not give leaves the span without it:
    missing rather than 0 (R11.20 row 5).
    """
    if tokens.input is None or tokens.output is None:
        return None
    return {
        "input_tokens": tokens.input,
        "output_tokens": tokens.output,
        "total_tokens": tokens.input + tokens.output,
    }


def token_metrics(tokens: Tokens) -> dict[str, int]:
    """A run's `tokens_in` and `tokens_out`, or neither when a side went unreported.

    The sums R5.12 prints, handed to the record rather than worked out again
    (spec 011). A run that asked nothing spent `0`, which is a count; a run with
    a call its provider did not report records no figure at all (R11.20).
    """
    if tokens.input is None or tokens.output is None:
        return {}
    return {"tokens_in": tokens.input, "tokens_out": tokens.output}


def _spent(tokens: Tokens | None) -> str:
    """The token clause of a step's line, or nothing for a step that asked nothing."""
    if tokens is None:
        return ""
    if tokens.input is None or tokens.output is None:
        return " · tokens not reported"
    return f" · {tokens.input:,} tokens in · {tokens.output:,} out"


def judge_line(*, field: str, agreement: float, cases: int, judge_model: str) -> str:
    """The line `dossier calibrate` prints for one judged field (R7.14).

    Here for the reason `step_line` is: the terminal and the record's
    description hold the same measurement, and holding it twice is how the file,
    the terminal and MLflow start to disagree (spec 011).

    The field is padded so a column of fields lines up in the terminal. A
    description strips it, which is why the padding is on the left of the figure
    and not between it and the judge.
    """
    plural = "" if cases == 1 else "s"
    return f"{field:<18} {agreement:.1%} agreement over {cases} case{plural} · {judge_model}"


def statistics_line(calibration: Calibration, *, field: str = "") -> str | None:
    """The line under a judge's agreement line: what the agreement hides (R7.29).

    Indented to start where the agreement line's figure starts, so the eye
    reads down one column of figures; `field` is the judge line's, for a name
    long enough to push that figure right. In plain words, because the person
    reading it agrees the bar and may never have met a Wilson interval.

    A figure that is not measurable is said to be, never printed as 0 or 100%
    (R7.27, R7.28). `None` for a calibration written before these figures
    existed: there is nothing to say that the file does not hold.
    """
    if calibration.lower_bound is None:
        return None
    measured_kappa = (
        "kappa not measurable"
        if calibration.kappa is None
        else f"kappa {calibration.kappa:.2f}"
    )
    halves = [
        f"{name} {half.agreed} of {half.cases}" if half.cases else f"no {name} case"
        for name, half in (
            ("supported", calibration.supported),
            ("unsupported", calibration.unsupported),
        )
        if half is not None
    ]
    figures = " · ".join(
        [f"lower bound {calibration.lower_bound:.1%}", measured_kappa, *halves]
    )
    return f"{'':<{len(f'{field:<18} ')}}{figures}"


def calibration_lines(field: str, calibration: Calibration) -> list[str]:
    """What `dossier calibrate` prints for one judge, and its record repeats (R7.29).

    One function for both, so the terminal and the description cannot hold
    different lines (R11.17): the agreement line, then what it hides.
    """
    lines = [
        judge_line(
            field=field,
            agreement=calibration.agreement,
            cases=calibration.sample_size,
            judge_model=calibration.judge_model,
        )
    ]
    hidden = statistics_line(calibration, field=field)
    return lines if hidden is None else [*lines, hidden]


def run_description(
    *, run_id: str, pipeline: str, model: str, pipeline_hash: str, lines: Sequence[str]
) -> str:
    """What a `dossier run` says about itself, in MLflow's Description (R11.17).

    The run id, the pin and the pipeline hash, then the step lines the command
    printed. The hash is shown at the width every other record shows it at
    (R10.10): sixty-four characters here would push the lines that matter off
    the card.
    """
    return _described(
        [
            f"run {run_id} · {pipeline}",
            f"model {model} · pipeline {pipeline_hash[:_DISPLAY_HASH]}",
        ],
        lines,
    )


def sync_description(*, pipeline: str, lines: Sequence[str]) -> str:
    """What a `dossier sync` says about itself (R11.17 row 3)."""
    return _described([f"sync {pipeline}"], lines)


def convert_description(*, pipeline: str, lines: Sequence[str]) -> str:
    """What a `dossier convert` says about itself (R11.17 row 4)."""
    return _described([f"convert {pipeline}"], lines)


def gc_description(*, lines: Sequence[str]) -> str:
    """What a `dossier gc --apply` says about itself: the lines it printed (R11.28, R11.17)."""
    return _described(["gc"], lines)


def calibration_description(
    *, pipeline: str, gold: str, gold_hash: str, lines: Sequence[str]
) -> str:
    """What a `dossier calibrate` says about itself (R11.17 row 5).

    The gold set is on the header and not in the lines, because a line is per
    field and the set is per run -- and because a second calibration of one
    field against edited answers is a different measurement that would otherwise
    read as identical (R7.14 row 2).
    """
    return _described(
        [f"calibrate {pipeline} · gold {_gold_name(gold)} {gold_hash[:_DISPLAY_HASH]}"], lines
    )


def _described(header: Sequence[str], lines: Sequence[str]) -> str:
    """A header, then the command's own lines with their indentation removed.

    Handed over rather than recomposed: what the command printed is what the
    record holds, so a figure that moves in one and not the other fails a test
    instead of drifting (R11.17). Blank lines are dropped -- MLflow renders the
    description as markdown, and a trailing blank reads as a paragraph break
    before nothing.
    """
    return "\n".join([*header, *(line.strip() for line in lines if line.strip())])


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
    metrics: dict[str, float] = {
        f"judge/{field}/agreement": percentage,
        f"judge/{field}/cases": calibration.sample_size,
    }
    # What the agreement hides (R7.29), rounded as `statistics_line` prints it.
    # A figure that is not measurable is left out rather than sent as 0:
    # MLflow has no null, and a 0 would be charted as a judge that scored 0.
    if calibration.lower_bound is not None:
        metrics[f"judge/{field}/lower_bound"] = round(calibration.lower_bound * 100, 1)
    if calibration.kappa is not None:
        metrics[f"judge/{field}/kappa"] = round(calibration.kappa, 2)
    for name, half in (
        ("supported", calibration.supported),
        ("unsupported", calibration.unsupported),
    ):
        if half is not None and half.rate is not None:
            metrics[f"judge/{field}/{name}"] = round(half.rate * 100, 1)
    return (
        {
            f"judge/{field}/model": calibration.judge_model,
            f"judge/{field}/rubric": calibration.rubric_hash,
        },
        metrics,
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


def trace_request(
    document: str, values: Mapping[str, str], *, capture: str
) -> dict[str, object]:
    """What a trace was asked about, as the trace list's Request shows it (R15.1).

    The document key, and each value the step was handed under its input's name,
    as the prompt was rendered with them (R3.13). The values sit under `inputs`
    of their own, so a step that happens to be called `document` cannot stand in
    for the key. Under `hashes`, each value is its hash and no word of it is
    held, as no span holds one (R10.8).
    """
    if capture == "hashes":
        values = {name: content_hash(value.encode("utf-8")) for name, value in values.items()}
    return {"document": document, "inputs": dict(values)}


def trace_response(
    text: str | None, *, structured: bool, error: str | None, capture: str
) -> object:
    """What a trace answered, as the trace list's Response shows it (R15.1).

    The answer as `runs/` holds it (R0.11): a field record parsed, so MLflow
    renders it as the object it is rather than as a quoted string, and prose as
    written. A document that failed answered nothing, and shows the error it
    failed with -- the one the trace already carries (R11.1 row 4). Under
    `hashes`, the artifact's hash (R10.8).
    """
    if error is not None or text is None:
        return {"error": error}
    if capture == "hashes":
        return {"artifact": content_hash(text.encode("utf-8"))}
    return json.loads(text) if structured else text


def trace_pages(
    pages: Sequence[tuple[str, str]], *, structured: bool, capture: str
) -> dict[str, object]:
    """What a `per_part` document's trace answered: each page's, under its name (R15.6).

    `runs/` holds a `per_part` document as one file per page, so its answer is
    shown the same way, each page as R15.1 shows a document. The joined text a
    later step reads wraps every page in a `<part>` tag and is not JSON; parsed
    as one, it stopped every `per_part` run recorded to MLflow after its first
    document.
    """
    return {
        name: trace_response(text, structured=structured, error=None, capture=capture)
        for name, text in pages
    }


# The tag the review queue filters on, and the tag saying why (R15.2).
REVIEW = "dossier.review"
FINDINGS = "dossier.findings"


def record_content[T](build: Callable[[], T], *, otherwise: Callable[[str], T]) -> T:
    """What `build` makes of a record's content, or what `otherwise` makes of why not (R10.25).

    A document's trace is built inside the run's loop, before the best-effort
    tracker is handed anything (R10.6), so an exception building it was the
    run's: one stopped every `per_part` run recorded to MLflow after its first
    document (R15.6). Here the failure becomes the record's content instead,
    and the run goes on as it would have untracked.
    """
    try:
        return build()
    except Exception as error:
        return otherwise(f"could not be built: {type(error).__name__}: {error}")


def unbuilt_tags(why: str) -> dict[str, str]:
    """A trace's tags where its own could not be built: in the queue, saying why (R10.25).

    A doubt nobody could write down is still a doubt, so the trace is put where
    a reviewer looks rather than left out of it (R15.2).
    """
    return {REVIEW: "needed", FINDINGS: why}


def review_tags(
    *, failed: bool, verdicts: Sequence[tuple[str, FieldVerdict]]
) -> dict[str, str]:
    """The tags that put a trace in the review queue, or none (R15.2).

    A doubt is what the run itself was not sure of: a document that failed, and
    a field `ungrounded` or `invalid` (R6.16). Not a `described` field, which a
    judge decides (R7.21), nor an abstention, which is a valid answer (R6.5).
    The fields are named sorted, with why, so the reason is on the row and two
    runs of one answer tag it identically (R0.4).
    """
    if failed:
        return {REVIEW: "needed", FINDINGS: "failed"}
    doubts = sorted(
        f"{field}: {verdict.value}" for field, verdict in verdicts if verdict.is_failure
    )
    if not doubts:
        return {}
    return {REVIEW: "needed", FINDINGS: "; ".join(doubts)}
