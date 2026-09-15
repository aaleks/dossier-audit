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

ENABLED = "DOSSIER_MLFLOW_ENABLED"
TRACKING_URI = "DOSSIER_MLFLOW_TRACKING_URI"
EXPERIMENT = "DOSSIER_MLFLOW_EXPERIMENT"

# One experiment per pipeline and command kind: a sync's fetch counts, a run's
# traces and an eval's per-field accuracy are not comparable with one another,
# so they do not share an experiment unless someone asks them to (spec 010).
DEFAULT_EXPERIMENT = "dossier-audit/{pipeline}/{kind}"

# Exactly spec 010's placeholders. `{gold}` exists only for `eval`.
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


def _gold_name(gold: str) -> str:
    """`incidents` from `gold/incidents` or `gold/incidents/`: the set's own name."""
    return gold.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
