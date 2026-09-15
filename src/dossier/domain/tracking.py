"""Tracking decisions (spec 010): whether it is on, and what may be recorded.

Pure. The environment arrives as a mapping that `dossier.config` reads and hands
in -- this layer reads nothing itself -- which is what lets every decision here
be tested with a dict.

Tracking observes a run and is never an input to one (R0.10): nothing decided
here enters a key, a manifest or a score.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

ENABLED = "DOSSIER_MLFLOW_ENABLED"
TRACKING_URI = "DOSSIER_MLFLOW_TRACKING_URI"


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
