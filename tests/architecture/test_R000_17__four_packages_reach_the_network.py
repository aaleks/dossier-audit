"""R0.17 — exactly four packages may reach the network, a model is asked only on
a cache miss, and what a search reads of the index enters no key, manifest or
score.

`dossier.infrastructure.connectors` fetches source payloads;
`dossier.infrastructure.models` asks a model, for an answer or for a vector;
`dossier.infrastructure.tracking` sends records to MLflow;
`dossier.infrastructure.index` writes the embedding index (spec 018) and
searches it (spec 019). Nothing else imports a network client, on any code
path, including error paths and imports made lazily inside a function body.

Supersedes R0.16, which fenced what is read back from the index to ids and
content hashes before there was a search; R0.10, which admitted three
packages; and R0.9's two. Each widening counted the new package's client as a
network client (`mlflow` then, `psycopg` later), so that the exemption has
teeth: without that, the check would pass green while the client was imported
anywhere.

The index is still derived data. `IndexSink` reads back only the ids and
content hashes of what it holds, to write only what changed (R18.4). A search
reads back chunks through its own port, `IndexSearch`, and what it reads
reaches the terminal and MLflow: nothing the index holds can enter a key, a
manifest or a score (rows 11 and 12).
"""

from __future__ import annotations

import inspect
import typing
from pathlib import Path

import pytest

from .imports_scan import (
    INDEX,
    REACH_THE_NETWORK,
    TRACKING,
    Import,
    imports_of,
    is_network,
    module_files,
    module_name,
)

MODULES = module_files()


def _left_of_the_boundary(name: str) -> bool:
    return name.startswith(REACH_THE_NETWORK)


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_no_network_import_outside_the_four_permitted_packages(path):
    """Rows 1, 2, 4 and 6: a network import anywhere else is a violation."""
    if _left_of_the_boundary(module_name(path)):
        return
    offenders: list[Import] = [i for i in imports_of(path) if is_network(i.module)]
    assert not offenders, "\n".join(
        f"{i.where}: imports {i.module!r}"
        + (" inside a function body -- a lazy import is still an import" if i.lazy else "")
        + f"\n  {module_name(path)} may not reach the network (R0.17)."
        f"\n  Fix: move the call into one of {REACH_THE_NETWORK} and pass the "
        "result across."
        for i in offenders
    )


def test_exactly_four_packages_are_exempt_and_the_index_is_the_fourth():
    """Rows 3 and 5: tracking and the index sink are left of the line.

    The line that admitted a fourth package is this one. A fifth is a change to
    the hash boundary, not a detail.
    """
    assert len(REACH_THE_NETWORK) == 4, (
        "a fifth exempt package is a change to the hash boundary, not a detail"
    )
    assert TRACKING in REACH_THE_NETWORK
    assert INDEX in REACH_THE_NETWORK
    assert _left_of_the_boundary(f"{TRACKING}.mlflow")
    assert _left_of_the_boundary(f"{INDEX}.postgres"), (
        "the Postgres sink in dossier/infrastructure/index/postgres.py is the fourth package"
    )


def test_the_clients_of_the_exempt_packages_count_as_network_clients():
    """Rows 4 and 6, the half that gives each exemption teeth.

    `mlflow` reaches a tracking server and `psycopg` a database, whatever they
    are named. Uncounted, `application/run.py` or `application/embed.py` could
    import either and the check would stay green.
    """
    for client in ("mlflow", "mlflow.tracking", "psycopg", "psycopg.rows", "pgvector.psycopg"):
        assert is_network(client), f"{client} must count as a network client"
    for sdk in ("anthropic", "openai", "cohere", "litellm", "ollama", "asyncpg", "psycopg2"):
        assert is_network(sdk), f"{sdk} must count as a network client"


def test_the_tracker_port_reads_nothing_back_from_the_server():
    """Row 3's promise: the `Tracker` port declares no method that returns anything.

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


def test_the_index_port_reads_back_only_ids_and_content_hashes():
    """Row 7: `IndexSink` returns nothing but what `held` answers, ids to hashes.

    The index is derived data. A method returning anything else read from it
    would be the first way for the index to become an input to `dossier`.
    """
    from dossier.domain.ports import IndexSink

    methods = {
        name: member
        for name, member in vars(IndexSink).items()
        if callable(member) and not name.startswith("_")
    }
    assert set(methods) == {"prepare", "held", "write", "remove"}
    returning = {
        name: typing.get_type_hints(member).get("return") for name, member in methods.items()
    }
    assert {name for name, hint in returning.items() if hint is not type(None)} == {"held"}
    assert str(returning["held"]) == "collections.abc.Mapping[str, str]"


def test_the_paths_that_must_never_ask_or_record_cannot_be_handed_a_client():
    """Row 8: `--plan` makes zero model calls and zero tracking calls.

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


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_local_file_io_is_not_network_io(path):
    """Row 9, counter-example: `pathlib` and `open` are fine everywhere.

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


class TestTheOnePermittedCrossings:
    """Row 10, and R0.10's row 8: a model is handed over only where a miss asks it.

    A stage with no cache entry asks the model, once (R5.5). A chunk with no
    cached vector asks the embedding model, once (R18.3). Both are taken as
    arguments, built left of the line, so nothing right of it constructs one.
    """

    def test_a_stage_on_a_cache_miss_takes_the_model(self):
        from dossier.application.run import execute

        assert "model" in inspect.signature(execute).parameters

    def test_an_embed_takes_the_embedding_model_and_the_index_as_arguments(self):
        from dossier.application.embed import embed_index

        parameters = inspect.signature(embed_index).parameters
        assert {"embedder", "sink", "vectors"} <= set(parameters)


class TestTheDetectorDetects:
    """Rows 1, 2, 4 and 6, asserted against modules written for the test.

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
        """Row 1: the one where `convert.py` imports `httpx`."""
        assert self.probe(tmp_path, "import httpx\n") == ["httpx"]

    def test_a_lazy_import_inside_a_function_is_still_an_import(self, tmp_path: Path):
        """Row 2: the one where `urllib.request` hides in a function body."""
        source = "def fetch():\n    from urllib import request\n    return request\n"

        assert "urllib.request" in self.probe(tmp_path, source)

    def test_an_mlflow_import_is_caught(self, tmp_path: Path):
        """Row 4: the one where `application/run.py` imports `mlflow`."""
        assert self.probe(tmp_path, "import mlflow\n") == ["mlflow"]

    def test_a_psycopg_import_is_caught(self, tmp_path: Path):
        """Row 6: the one where `application/embed.py` imports `psycopg`."""
        assert self.probe(tmp_path, "import psycopg\n") == ["psycopg"]

    def test_an_innocent_module_is_not_flagged(self, tmp_path: Path):
        """The one that stops the detector crying wolf."""
        source = "import json\nfrom pathlib import Path\nfrom dossier.domain import keys\n"

        assert self.probe(tmp_path, source) == []


# Where keys, manifests and scores are made: nothing a search reads may reach them.
COMPOSERS = (
    "dossier/domain/keys.py",
    "dossier/application/run.py",
    "dossier/application/eval.py",
)


def _reads_a_search(path: Path) -> list[str]:
    """Each import in `path` of what a search reads: the search module, or its port."""
    return [
        found.where
        for found in imports_of(path)
        if found.module.startswith(("dossier.domain.search", "dossier.application.search"))
        or found.module.endswith(".IndexSearch")
    ]


@pytest.mark.parametrize("composer", COMPOSERS)
def test_nothing_a_search_reads_enters_a_key_a_manifest_or_a_score(composer: str):
    """Row 11: keys, the run and eval import neither the search nor its port."""
    path = Path(__file__).resolve().parents[2] / "src" / composer

    assert path.is_file(), composer
    assert _reads_a_search(path) == [], f"{composer} imports what a search reads"


def test_a_search_is_where_the_index_is_read():
    """Row 12, counter-example: `application/search.py` imports the port, and may."""
    path = Path(__file__).resolve().parents[2] / "src" / "dossier" / "application" / "search.py"

    assert _reads_a_search(path), "application/search.py should import IndexSearch"


class TestTheSearchDetectorDetects:
    """Row 11's check has teeth: an import of either kind is seen."""

    def test_an_import_of_the_port_is_seen(self, tmp_path: Path):
        module = tmp_path / "keys.py"
        module.write_text("from dossier.domain.ports import IndexSearch\n", encoding="utf-8")

        assert len(_reads_a_search_any(module)) == 1

    def test_an_import_of_the_decisions_is_seen(self, tmp_path: Path):
        module = tmp_path / "eval.py"
        module.write_text("def f():\n    from dossier.domain.search import fused\n", "utf-8")

        assert len(_reads_a_search_any(module)) >= 1


def _reads_a_search_any(path: Path) -> list[str]:
    """`_reads_a_search` for a file outside the repository, by module name only."""
    return [
        found.module
        for found in imports_of(path)
        if found.module.startswith(("dossier.domain.search", "dossier.application.search"))
        or found.module.endswith(".IndexSearch")
    ]
