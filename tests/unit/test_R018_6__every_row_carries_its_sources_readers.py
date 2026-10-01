"""R18.6 — every row carries the readers its source declares, and a source
declaring none is not indexed.

`dossier` fetches no permissions: no Jira security level, no Confluence page
restriction. An index built without a decision about who may read it makes a
restricted page searchable by anyone who can query the database. So each source
an index reads declares its readers in `sources.yaml`, every row carries them,
and a source that has not declared any is refused before anything is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.domain.index import Embedded, indexed
from dossier.domain.pipeline import SourceConfig

MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
INDEX = f"""\
pipeline: incident-audit
embedding_model: {MODEL}
chunker: {{name: headings, max_chars: 2000}}
target: {{dsn_env: DOSSIER_INDEX_DSN}}
"""


def load(workspace: Path, sources: list[SourceConfig]):
    from dossier.config.load import load_index

    path = workspace / "indexes" / "incidents.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(INDEX, encoding="utf-8")
    return load_index(path, providers=PROVIDERS, sources=sources)


def chunk(text: str, at: int) -> Embedded:
    return Embedded(
        chunk_id=f"{at:064x}",
        kind="body",
        chunk_index=at,
        heading_path=("INC-4821 — Card payments declined at checkout",),
        text=text,
        embedding=(0.25, -0.25),
    )


class TestEveryRowCarriesItsSourcesReaders:
    """R18.6 — the readers on every row, and no row without them."""

    def test_a_document_and_each_of_its_chunks_carry_the_sources_readers(self):
        """Row 1 — the one where `incidents-jira` declares `incident-response`."""
        document, chunks = indexed(
            index="incidents",
            source_id="incidents-jira",
            key="INC-4821",
            title="INC-4821 — Card payments declined at checkout",
            snapshot="a3f9c1e2" * 8,
            acl=("incident-response",),
            embedding_model=MODEL,
            chunks=[chunk("**Status:** Done", 0), chunk("CHF 48'200 in interest.", 1)],
        )

        assert document.acl == ("incident-response",)
        assert [held.acl for held in chunks] == [("incident-response",)] * 2

    def test_a_source_declaring_no_readers_is_refused_at_load(self, tmp_path: Path):
        """Row 2, counter-example — the one whose source never said who may read it."""
        from dossier.config.load import ConfigError

        write_pipeline(tmp_path, sources=["procedures-confluence"])

        with pytest.raises(ConfigError) as refused:
            load(tmp_path, [SourceConfig(id="procedures-confluence", type="confluence")])

        assert str(refused.value) == (
            "incidents.yaml: incident-audit reads 'procedures-confluence', which "
            "declares no readers. Add `acl: [<who may read it>]` to it in "
            "sources.yaml: nothing is indexed before someone decides who may search it"
        )

    def test_an_empty_list_of_readers_is_refused(self, tmp_path: Path):
        """Row 3, counter-example — the one declaring `acl: []`.

        Refused when `sources.yaml` loads, whether or not an index reads it.
        """
        from dossier.config.load import ConfigError, load_sources
        from dossier.infrastructure.connectors.folder import FolderKeys

        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n  - id: incidents-manual\n    type: folder\n"
            "    path: inbox/incidents/\n    acl: []\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as refused:
            load_sources(path, connectors={"folder": FolderKeys})

        assert str(refused.value) == (
            "sources.yaml, line 5: in 'incidents-manual', 'acl' -- Value error, acl: an "
            "empty list names no reader, and is not a decision about who may read this "
            "source. Name who may, as acl: [incident-response]"
        )

    def test_each_source_s_readers_reach_its_own_rows(self, tmp_path: Path):
        """Row 1, through `embed`: two sources, two sets of readers, never mixed.

        A restricted source's readers on another source's rows would expose
        them, so every document and every chunk is checked against its own.
        """
        from tests.fakes import FakeEmbeddingProvider, FakeIndexSink
        from tests.unit.test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss import (
            declaration,
        )

        from dossier.application.embed import ToIndex, embed_index
        from dossier.domain.chunks import HeadingsChunker
        from dossier.infrastructure.cache import ArtifactCache

        readers = {
            "incidents-jira": ("incident-response",),
            "procedures-confluence": ("operations", "incident-response"),
        }
        sink = FakeIndexSink()
        embed_index(
            declaration=declaration(),
            documents=[
                ToIndex(
                    "incidents-jira", "INC-4821", "a3f9c1e2", "# INC-4821\n\nCHF 48'200.\n"
                ),
                ToIndex(
                    "procedures-confluence", "OPS-114", "77c1b40a", "# OPS-114\n\nEscalate.\n"
                ),
            ],
            readers=readers,
            chunker=HeadingsChunker(max_chars=2000),
            embedder=FakeEmbeddingProvider(),
            vectors=ArtifactCache(tmp_path, namespace="embed"),
            sink=sink,
        )

        for document in sink.held_documents("incidents"):
            assert document.acl == readers[document.source_id]
        for chunk in sink.held_chunks("incidents"):
            source = chunk.document_id.partition(":")[0]
            assert chunk.acl == readers[source]
        assert {chunk.acl for chunk in sink.held_chunks("incidents")} == set(readers.values())

    def test_a_source_declaring_readers_loads(self, tmp_path: Path):
        """Row 1's source, at load: it declares readers, so the index loads."""
        write_pipeline(tmp_path, sources=["incidents-jira"])

        index = load(
            tmp_path,
            [SourceConfig(id="incidents-jira", type="jira", acl=["incident-response"])],
        )

        assert index.pipeline == "incident-audit"
