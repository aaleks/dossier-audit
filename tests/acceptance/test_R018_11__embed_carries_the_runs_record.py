"""R18.11 — what `dossier embed` carries of a run is the latest run's grounded
record of the snapshot it holds.

The outer loop of spec 018's second slice. A person syncs, runs the pipeline
that extracts the taxonomy, and embeds: the index holds the categories the run
grounded as values to filter on, and the free text as one more chunk to
search. When the document changes after the run, its record goes, because it
describes text that is no longer there; the next run brings it back.

The model answering the run is scripted per document, and the embedding model
and the index are fakes, as in R18.7.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import (
    DSN_ENV,
    EMBEDDING_MODEL,
    _cli,
)
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import SOURCE_ID, SOURCE_TYPE, IssueTracker, RoutedModel, found

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
INDEX = "incidents"
ROOT_CAUSE = (
    "Certificate renewal and certificate deployment were two separate processes, "
    "and only the first was automated."
)
NOTE = (
    "# INC-4830\n\n"
    "Checkout returned 502 after the TLS certificate expired.\n\n"
    "## Root cause\n\n"
    f"{ROOT_CAUSE}\n\n"
    "## Contributing factors\n\n"
    "The 30-day expiry alert was routed to an archived Slack channel.\n"
)
EDITED = NOTE.replace("an archived Slack channel", "a Slack channel archived in May 2026")
TAXONOMY = """\
fields:
  failure_category: {kind: enum, values: [certificate-expiry, capacity-exhaustion]}
  component:        {kind: enum, values: [checkout, payments-api]}
  root_cause:       {kind: free_text, judge: rubrics/root_cause.md}
"""
ANSWERS = {
    "INC-4830": [
        found("INC-4830", "failure_category", "certificate-expiry", "the TLS certificate expired"),
        found("INC-4830", "component", "checkout", "Checkout returned 502"),
        found("INC-4830", "root_cause", ROOT_CAUSE, ROOT_CAUSE),
    ]
}
DECLARATION = f"""\
pipeline: {PIPELINE}
embedding_model: {EMBEDDING_MODEL}
chunker: {{name: headings, max_chars: 2000}}
fields:
  filter: [failure_category, component]
  embed: [root_cause]
target: {{dsn_env: {DSN_ENV}}}
"""


@pytest.fixture
def issues() -> dict[str, str]:
    return {"INC-4830": NOTE}


@pytest.fixture
def embedder() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def index() -> FakeIndexSink:
    return FakeIndexSink()


@pytest.fixture
def run_once(workspace: Path, monkeypatch, issues, embedder, index) -> Path:
    """`INC-4830` synced and run, extracting its taxonomy, with the index declared."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n"
        "    acl: [incident-response]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace, sources=[SOURCE_ID], outputs={"extract": "schemas/taxonomy.yaml"}
    )
    schema = workspace / "pipelines" / PIPELINE / "schemas" / "taxonomy.yaml"
    schema.write_text(TAXONOMY, encoding="utf-8")
    (workspace / "indexes").mkdir()
    (workspace / "indexes" / f"{INDEX}.yaml").write_text(DECLARATION, encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(issues)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    monkeypatch.setattr(
        cli, "build_embedding_provider", lambda model_id: embedder, raising=False
    )
    monkeypatch.setattr(cli, "build_index_sink", lambda dsn: index, raising=False)
    monkeypatch.setenv(DSN_ENV, "postgresql://dossier@127.0.0.1:5435/dossier")
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return workspace


def _latest_run(workspace: Path) -> str:
    return sorted(path.name for path in (workspace / "runs").iterdir())[-1]


def _document(index: FakeIndexSink):
    (document,) = index.held_documents(INDEX)
    return document


def _records(index: FakeIndexSink) -> list:
    return [chunk for chunk in index.held_chunks(INDEX) if chunk.kind == "record"]


class TestEmbedCarriesTheRunsRecord:
    """R18.11 — the latest run's grounded record, of the snapshot held, or none."""

    def test_the_runs_grounded_categories_and_free_text_are_carried(
        self, run_once: Path, monkeypatch, index
    ):
        """Row 1 — the one synced, run and embedded."""
        result = _cli(run_once, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        document = _document(index)
        assert document.values == {
            "component": "checkout",
            "failure_category": "certificate-expiry",
        }
        assert document.run_id == _latest_run(run_once)
        assert [chunk.text for chunk in _records(index)] == [f"root_cause: {ROOT_CAUSE}"]

    def test_a_record_of_an_earlier_snapshot_is_removed_and_named(
        self, run_once: Path, monkeypatch, issues, embedder, index
    ):
        """Row 2 — the one changed and re-synced after the run."""
        assert _cli(run_once, monkeypatch, "embed", INDEX).exit_code == 0
        asked = len(embedder.texts)
        issues["INC-4830"] = EDITED
        assert _cli(run_once, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(run_once, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        run = _latest_run(run_once)
        assert f"INC-4830: record stale: {run} read an earlier snapshot" in (
            result.output.splitlines()
        ), result.output
        assert _records(index) == []
        assert _document(index).run_id is None
        assert embedder.texts[asked:] == [
            "INC-4830 > Contributing factors\n\n"
            "The 30-day expiry alert was routed to a Slack channel archived in May 2026."
        ]

    def test_the_next_run_brings_the_record_back(
        self, run_once: Path, monkeypatch, issues, index
    ):
        """Row 3, counter-example — the one run again after the change."""
        assert _cli(run_once, monkeypatch, "embed", INDEX).exit_code == 0
        issues["INC-4830"] = EDITED
        for args in (("sync", PIPELINE), ("run", PIPELINE)):
            assert _cli(run_once, monkeypatch, *args).exit_code == 0

        result = _cli(run_once, monkeypatch, "embed", INDEX)

        assert result.exit_code == 0, result.output
        assert _document(index).run_id == _latest_run(run_once)
        assert [chunk.text for chunk in _records(index)] == [f"root_cause: {ROOT_CAUSE}"]
