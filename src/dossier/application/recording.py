"""Closing the MLflow run of a command that stopped inside it (R11.23).

Two commands open their run before the work they record: `dossier run`, whose
traces are written while its steps run, and `dossier calibrate`, whose traces
are written case by case. Either can stop with the run open -- a model that is
unreachable, an interrupt -- and a run left `RUNNING` reads as a command still
at work, forever.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress

from dossier.domain.ports import Tracker


@contextmanager
def failed_if_stopped(tracker: Tracker | None) -> Iterator[None]:
    """Close the open run `FAILED` if the block stops, and let what stopped it go on.

    Closing the record is not handling the error: the same exception leaves,
    so the command exits as it would have with tracking off. A tracker that
    fails to close is swallowed for the same reason -- a lost record never
    changes a command's outcome (R10.6), and a `ConnectionError` from a server
    that went away must not replace the model error the person needs to read.
    """
    try:
        yield
    except BaseException:
        if tracker is not None:
            with suppress(Exception):
                tracker.end_run(status="FAILED")
        raise
