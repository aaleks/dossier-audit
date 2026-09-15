"""R0.10 — exactly three packages may reach the network, and a model is asked only
on a cache miss.

`dossier.infrastructure.connectors` fetches source payloads;
`dossier.infrastructure.models` asks a model; `dossier.infrastructure.tracking`
sends records to MLflow (spec 010). Nothing else imports a network client, on
any code path, including error paths and imports made lazily inside a function
body.

Supersedes R0.9, which admitted two -- and did not count `mlflow` as a network
client, so its check would have passed green while it was imported anywhere.
Widening the exemption is the decision; counting `mlflow` is what gives it teeth.

The third package changes nothing about what the boundary promises. Tracking
only *sends*: the port it is reached through has no method that returns anything
read from the server, so nothing MLflow holds can enter a key, a manifest or a
score (R10.4).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from .imports_scan import (
    REACH_THE_NETWORK,
    Import,
    imports_of,
    is_network,
    module_files,
    module_name,
)

MODULES = module_files()
TRACKING = "dossier.infrastructure.tracking"


def _left_of_the_boundary(name: str) -> bool:
    return name.startswith(REACH_THE_NETWORK)


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_no_network_import_outside_the_three_permitted_packages(path):
    """Examples 1, 2 and 4: a network import anywhere else is a violation."""
    if _left_of_the_boundary(module_name(path)):
        return
    offenders: list[Import] = [i for i in imports_of(path) if is_network(i.module)]
    assert not offenders, "\n".join(
        f"{i.where}: imports {i.module!r}"
        + (" inside a function body -- a lazy import is still an import" if i.lazy else "")
        + f"\n  {module_name(path)} may not reach the network (R0.10)."
        f"\n  Fix: move the call into one of {REACH_THE_NETWORK} and pass the "
        "result across."
        for i in offenders
    )


def test_exactly_three_packages_are_exempt_and_tracking_is_the_third():
    """Example 3: the exemption is three packages, and widening it is a decision.

    The line that admitted a third package is this one. A fourth is a change to
    the hash boundary, not a detail.
    """
    assert len(REACH_THE_NETWORK) == 3, (
        "a fourth exempt package is a change to the hash boundary, not a detail"
    )
    assert TRACKING in REACH_THE_NETWORK
    assert _left_of_the_boundary(f"{TRACKING}.mlflow"), (
        "the MLflow adapter in dossier/infrastructure/tracking/mlflow.py is the third package"
    )


def test_mlflow_counts_as_a_network_client():
    """Examples 3 and 4, the half that gives the exemption teeth.

    `mlflow` reaches a tracking server over HTTP whatever it is named. Under
    R0.9 it was not counted, so `application/run.py` could have imported it and
    the check would have stayed green.
    """
    assert is_network("mlflow")
    assert is_network("mlflow.tracking")
    for sdk in ("anthropic", "openai", "cohere", "litellm", "ollama"):
        assert is_network(sdk), f"{sdk} must count as a network client"


def test_the_tracker_port_reads_nothing_back_from_the_server():
    """Example 5: the `Tracker` port declares no method that returns anything.

    Tracking only sends. A method that returned something read from the server
    would be the first way for MLflow to become an input to a run (R10.4).
    """
    from dossier.domain.ports import Tracker

    methods = {
        name: member
        for name, member in vars(Tracker).items()
        if callable(member) and not name.startswith("_")
    }
    assert methods, "the Tracker port declares no methods at all"
    returning = {
        name: inspect.signature(member).return_annotation
        for name, member in methods.items()
        if inspect.signature(member).return_annotation not in (None, "None")
    }
    assert not returning, f"Tracker methods that return something: {returning}"


def test_the_paths_that_must_never_ask_or_record_cannot_be_handed_a_client():
    """Example 6: `--plan` makes zero model calls and zero tracking calls.

    R4.6 and R11.1 assert it behaviourally. This asserts the stronger and
    cheaper thing: planning, replaying and scoring have nowhere to put a model
    client or a tracker. A signature cannot drift the way a code path can.
    """
    from dossier.application.plan import build_plan
    from dossier.application.run import replay
    from dossier.domain.scoring import score_document, score_field

    for callable_ in (build_plan, replay, score_field, score_document):
        parameters = set(inspect.signature(callable_).parameters)
        assert not parameters & {"model", "client", "model_client", "tracker"}, (
            f"{callable_.__name__} takes something that could reach a model or a tracker"
        )


def test_a_stage_on_a_cache_miss_is_the_one_place_a_model_is_handed_over():
    """Counter-example (row 8): the one permitted crossing.

    Executing a run takes a model client, because a stage with no cache entry
    asks it -- once, and the answer is cached with its provenance record. R5.5
    is the claim that it never happens twice for the same inputs.
    """
    from dossier.application.run import execute

    assert "model" in inspect.signature(execute).parameters


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_local_file_io_is_not_network_io(path):
    """Counter-example (row 7): `pathlib` and `open` are fine everywhere.

    Stated as a test so that a future tightening of the network list cannot
    quietly start rejecting the store, which reads and writes local files by
    design (R0.2).
    """
    for imported in imports_of(path):
        if imported.root in {"pathlib", "shutil", "os", "io", "sqlite3"}:
            assert not is_network(imported.module), (
                f"{imported.where}: {imported.module!r} classified as network. "
                "Local file IO is not network IO -- fix NETWORK_MODULES."
            )


class TestTheDetectorDetects:
    """Examples 1, 2 and 4, asserted against modules written for the test.

    Every check above walks the real modules and asserts the offender list is
    empty. Nothing there would notice if `is_network` or `imports_of` silently
    stopped working, so a violating module is constructed and must be caught.
    """

    def probe(self, tmp_path: Path, source: str) -> list[str]:
        module = tmp_path / "probe.py"
        module.write_text(source, encoding="utf-8")
        return [
            imported.module for imported in imports_of(module) if is_network(imported.module)
        ]

    def test_a_plain_network_import_is_caught(self, tmp_path: Path):
        """Example 1: the one where `convert.py` imports `httpx`."""
        assert self.probe(tmp_path, "import httpx\n") == ["httpx"]

    def test_a_lazy_import_inside_a_function_is_still_an_import(self, tmp_path: Path):
        """Example 2: the one where `urllib.request` hides in a function body."""
        source = "def fetch():\n    from urllib import request\n    return request\n"

        assert "urllib.request" in self.probe(tmp_path, source)

    def test_an_mlflow_import_is_caught(self, tmp_path: Path):
        """Example 4: the one where `application/run.py` imports `mlflow`."""
        assert self.probe(tmp_path, "import mlflow\n") == ["mlflow"]

    def test_an_innocent_module_is_not_flagged(self, tmp_path: Path):
        """The one that stops the detector crying wolf."""
        source = "import json\nfrom pathlib import Path\nfrom dossier.domain import keys\n"

        assert self.probe(tmp_path, source) == []
