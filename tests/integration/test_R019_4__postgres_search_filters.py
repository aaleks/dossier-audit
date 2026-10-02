"""R19.4 -- `--where FIELD=VALUE` keeps only the documents carrying that value,
and a field or value the index does not carry is refused.

Here, against a real PostgreSQL with pgvector. The refusals, and the spelling a
value is read in, are decided before the index is asked, and are proved against
a fake index in `test_R019_4__where_keeps_the_documents_carrying_a_value.py`.
This file proves the fake is a claim about the real one: that
`PostgresIndexSearch` keeps the documents carrying a value, whether they carry
it alone or among several (rows 1, 3, 4 and 8), in both of a search's lists,
and that a filtered list the HNSW scan would leave short is filled (row 7).

Beside them, what the same search does that spec 019's other rules rely on:
`--as` keeps the chunks a reader named may read (R19.10); the words list is
`websearch_to_tsquery('simple', ...)`, best first by `ts_rank_cd` ("How a
search ranks"); a chunk id breaks a tie (R19.1); and `models` and `snapshots`
read what R19.6 and R19.7 compare.

`live`: it needs a server, so it is out of the default suite and runs only when
`DOSSIER_INDEX_DSN` names one (`dev/index/docker-compose.yml`). Every test
writes into a schema of its own, dropped afterwards, so it never touches an
index anyone reads.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import pytest

psycopg = pytest.importorskip("psycopg")
pgvector = pytest.importorskip("pgvector")

from pgvector import HalfVector  # noqa: E402 -- after the extra is found
from pgvector.psycopg import register_vector  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402
from tests.fakes import FakeEmbeddingProvider  # noqa: E402

from dossier.domain.index import Embedded, indexed  # noqa: E402
from dossier.domain.search import Candidate, Described, Lists  # noqa: E402
from dossier.infrastructure.index.postgres import (  # noqa: E402
    PostgresIndexSearch,
    PostgresIndexSink,
)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("DOSSIER_INDEX_DSN"),
        reason="DOSSIER_INDEX_DSN names no index server (dev/index/docker-compose.yml)",
    ),
]

MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
COLUMN = "halfvec(2560)"
INDEX = "incidents"
SNAPSHOT = "a3f9c1e2"

# What each incident carries, as `embed` writes it: one value alone, two as a
# list (R18.9), or nothing, when the run grounded no value to filter on.
CARRIED = {
    "INC-4830": {"failure_category": "certificate-expiry", "component": "checkout"},
    "INC-4821": {"failure_category": "certificate-expiry", "component": "payments-api"},
    "INC-5641": {
        "failure_category": "migration-lock",
        "component": ["checkout", "payments-api"],
    },
    "INC-5102": {"failure_category": "out-of-memory", "component": "orders-api"},
    "INC-4977": {},
}


def meaning(text: str) -> tuple[float, ...]:
    """The 2,560 values `FakeEmbeddingProvider` gives `text`: one text, one vector."""
    return tuple(FakeEmbeddingProvider().embed([text])[0])


def write(
    sink: PostgresIndexSink,
    key: str,
    text: str,
    *,
    source: str = "incidents-jira",
    acl: tuple[str, ...] = ("incident-response",),
    values: dict | None = None,
    title: str | None = None,
    chunk_id: str | None = None,
    snapshot: str = SNAPSHOT,
    model: str = MODEL,
    index: str = INDEX,
    embedding: tuple[float, ...] | None = None,
) -> str:
    """One document of one body chunk, written as `dossier embed` writes it; its id."""
    row, chunks = indexed(
        index=index,
        source_id=source,
        key=key,
        title=title or key,
        snapshot=snapshot,
        acl=acl,
        embedding_model=model,
        chunks=[
            Embedded(
                chunk_id=chunk_id or f"c-{key}",
                kind="body",
                chunk_index=0,
                heading_path=(title or key, "Summary"),
                text=text,
                embedding=embedding or meaning(text),
            )
        ],
        values=values,
    )
    sink.write(index, row, chunks)
    return row.document_id


def ask(
    search: PostgresIndexSearch,
    query: str,
    *,
    where: dict[str, list[str]] | None = None,
    readers: list[str] | None = None,
    candidates: int = 100,
    vector: tuple[float, ...] | None = None,
) -> Lists:
    return search.search(
        INDEX,
        vector=vector or meaning(query),
        words=query,
        where=where or {},
        readers=readers,
        candidates=candidates,
    )


def keys(candidates: tuple[Candidate, ...]) -> set[str]:
    return {candidate.document_id.partition(":")[2] for candidate in candidates}


def by_meaning_and_by_words(found: Lists) -> tuple[set[str], set[str]]:
    return keys(found.meaning), keys(found.words)


@pytest.fixture(scope="module")
def dsn() -> str:
    return os.environ["DOSSIER_INDEX_DSN"]


def _drop(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture
def schema(dsn: str):
    name = f"dossier_index_test_{uuid.uuid4().hex[:12]}"
    yield name
    _drop(dsn, name)


@pytest.fixture
def sink(dsn: str, schema: str):
    with PostgresIndexSink(dsn, schema=schema) as opened:
        opened.prepare(INDEX, COLUMN)
        yield opened


@pytest.fixture
def search(dsn: str, schema: str):
    with PostgresIndexSearch(dsn, schema=schema) as opened:
        yield opened


@pytest.fixture
def incidents(sink: PostgresIndexSink) -> None:
    """Five incidents, each a chunk whose words hold `incident`, so both lists hold all five."""
    for key, values in CARRIED.items():
        write(sink, key, f"{key} was declared an incident and resolved.", values=values)


class TestWhere:
    """Rows 1, 3, 4 and 8 -- a filter keeps the documents carrying a value, in both lists."""

    def test_no_filter_considers_every_document(self, incidents, search):
        """The one where nothing is filtered, and every document is in both lists (row 8)."""
        assert by_meaning_and_by_words(ask(search, "incident")) == (set(CARRIED), set(CARRIED))

    def test_a_value_is_found_whether_a_document_carries_it_alone_or_among_several(
        self, incidents, search
    ):
        """The one where `INC-5641` carries two components, and is found by either (row 1).

        A carried value is a JSON string, or a JSON array of strings when the
        run answered more than one (R18.9): `checkout` is `INC-4830`'s one
        value and one of `INC-5641`'s two.
        """
        checkout = ask(search, "incident", where={"component": ["checkout"]})
        payments = ask(search, "incident", where={"component": ["payments-api"]})

        assert by_meaning_and_by_words(checkout) == (
            {"INC-4830", "INC-5641"},
            {"INC-4830", "INC-5641"},
        )
        assert by_meaning_and_by_words(payments) == (
            {"INC-4821", "INC-5641"},
            {"INC-4821", "INC-5641"},
        )

    def test_two_fields_must_both_be_carried(self, incidents, search):
        """The one where only `INC-4830` carries both (row 3).

        `INC-4821` carries the category and not the component, and `INC-5641`
        the component and not the category.
        """
        found = ask(
            search,
            "incident",
            where={"failure_category": ["certificate-expiry"], "component": ["checkout"]},
        )

        assert by_meaning_and_by_words(found) == ({"INC-4830"}, {"INC-4830"})

    def test_one_field_given_twice_is_one_choice_of_values(self, incidents, search):
        """The one where `component` is `checkout` or `orders-api`, and three match (row 4)."""
        found = ask(search, "incident", where={"component": ["checkout", "orders-api"]})

        assert by_meaning_and_by_words(found) == (
            {"INC-4830", "INC-5641", "INC-5102"},
            {"INC-4830", "INC-5641", "INC-5102"},
        )

    def test_a_value_no_document_carries_finds_nothing_rather_than_everything(
        self, incidents, search
    ):
        """The one where nothing carries `meteor-strike`, and both lists are empty.

        `INC-4977` carries no value at all, and is found by no filter either.
        """
        found = ask(search, "incident", where={"failure_category": ["meteor-strike"]})

        assert found == Lists()


@dataclass(frozen=True)
class Corpus:
    """Row 7's index: 400 documents in a schema of their own, 10 `certificate-expiry`."""

    schema: str
    expiring: frozenset[str]
    # Nearest the other 390: every `certificate-expiry` document is among the
    # farthest from it, so a scan that stops at its first forty finds none.
    away: tuple[float, ...]


@pytest.fixture(scope="module")
def corpus(dsn: str):
    """400 documents, 1 in 40 carrying `certificate-expiry`, embedded as the fake embeds.

    The vectors are `FakeEmbeddingProvider`'s, of 2,560 values, so the HNSW
    index over them is a real one. The keys are generated, not incidents of
    `specs/_fixtures.md`: row 7 needs a count, not a story.
    """
    name = f"dossier_index_test_{uuid.uuid4().hex[:12]}"
    expiring: dict[str, tuple[float, ...]] = {}
    others = ("timeout", "out-of-memory", "migration-lock", "disk-full")
    try:
        with PostgresIndexSink(dsn, schema=name) as sink:
            sink.prepare(INDEX, COLUMN)
            for at in range(400):
                key = f"GEN-{at:03d}"
                text = f"{key}: requests failed at checkout"
                category = "certificate-expiry" if at % 40 == 7 else others[at % 4]
                write(sink, key, text, values={"failure_category": category})
                if category == "certificate-expiry":
                    expiring[key] = meaning(text)
        away = tuple(-sum(column) for column in zip(*expiring.values(), strict=True))
        yield Corpus(schema=name, expiring=frozenset(expiring), away=away)
    finally:
        _drop(dsn, name)


EXPIRING = {"failure_category": ["certificate-expiry"]}


class TestAFilteredListIsFilled:
    """Row 7 -- 400 documents, 10 carrying `certificate-expiry`: a list of 10 holds all 10."""

    def test_a_filter_one_document_in_forty_carries_still_fills_the_list(self, dsn, corpus):
        """The one where the planner picks its own plan, and the 10 come back."""
        with PostgresIndexSearch(dsn, schema=corpus.schema) as search:
            found = ask(search, "", where=EXPIRING, candidates=10, vector=corpus.away)

        assert len(found.meaning) == 10
        assert keys(found.meaning) == corpus.expiring

    def test_the_hnsw_scan_goes_on_past_the_chunks_it_first_reads_until_the_list_is_full(
        self, dsn, corpus
    ):
        """The one where the HNSW index is the only plan, and the scan does not stop at forty.

        On 400 rows the planner would rather read every chunk and sort them,
        which is exact and needs no iterative scan. Sequential scans and sorts
        are switched off for the session, so the list can only come from the
        HNSW index, as on a corpus large enough that the planner chooses it.

        The teeth: through the same plan, on the same data, a scan with
        `hnsw.iterative_scan = off` stops at its first `hnsw.ef_search` (40)
        chunks, filters them, and returns fewer than 10. Every
        `certificate-expiry` document is among the farthest from the query,
        so it returns none of them.
        """
        forced = make_conninfo(dsn, options="-c enable_seqscan=off -c enable_sort=off")

        with PostgresIndexSearch(forced, schema=corpus.schema) as search:
            found = ask(search, "", where=EXPIRING, candidates=10, vector=corpus.away)

        assert len(found.meaning) == 10
        assert keys(found.meaning) == corpus.expiring

        nearest = (
            f"SELECT c.chunk_id FROM {corpus.schema}.chunks c "
            f"JOIN {corpus.schema}.documents d "
            'ON d."index" = c."index" AND d.document_id = c.document_id '
            "WHERE c.\"index\" = %s AND (d.filter_values -> 'failure_category') ?| %s "
            "ORDER BY c.embedding <=> %s LIMIT 10"
        )
        params = (INDEX, ["certificate-expiry"], HalfVector(list(corpus.away)))
        with psycopg.connect(forced, autocommit=True) as connection:
            register_vector(connection)
            plan = "\n".join(
                line for (line,) in connection.execute("EXPLAIN " + nearest, params)
            )
            with connection.transaction():
                connection.execute("SET LOCAL hnsw.iterative_scan = off")
                stopped = connection.execute(nearest, params).fetchall()

        assert "Index Scan using chunks_embedding" in plan
        assert len(stopped) < 10


class TestReader:
    """R19.10 -- `--as READER`, repeatable, keeps what a reader named may read, both lists."""

    @pytest.fixture
    def sources(self, sink: PostgresIndexSink) -> None:
        write(sink, "INC-4830", "The certificate expired at checkout.")
        write(
            sink,
            "OPS-114",
            "Escalate a certificate expiry to the on-call SRE.",
            source="procedures-confluence",
            acl=("sre",),
            title="OPS-114 Incident escalation procedure",
        )

    def test_a_reader_is_handed_only_the_chunks_its_sources_declare_it_may_read(
        self, sources, search
    ):
        """The one where `incident-response` reads Jira, `sre` Confluence, and no reader both.

        `certificate` is in both chunks' words, so each list holds both before
        the reader is applied.
        """
        query = "certificate"

        assert by_meaning_and_by_words(ask(search, query, readers=["incident-response"])) == (
            {"INC-4830"},
            {"INC-4830"},
        )
        assert by_meaning_and_by_words(ask(search, query, readers=["sre"])) == (
            {"OPS-114"},
            {"OPS-114"},
        )
        assert by_meaning_and_by_words(ask(search, query)) == (
            {"INC-4830", "OPS-114"},
            {"INC-4830", "OPS-114"},
        )

    def test_two_readers_are_handed_what_either_may_read(self, sources, search):
        """Row 2 -- the one as `incident-response` and `sre`, in one search."""
        found = ask(search, "certificate", readers=["incident-response", "sre"])

        assert by_meaning_and_by_words(found) == (
            {"INC-4830", "OPS-114"},
            {"INC-4830", "OPS-114"},
        )

    def test_a_reader_and_a_filter_both_hold(self, sink, search):
        """The one where `INC-4830` carries the value, and only `incident-response` reads it."""
        write(
            sink, "INC-4830", "The certificate expired at checkout.", values=CARRIED["INC-4830"]
        )

        assert (
            keys(ask(search, "certificate", where=EXPIRING, readers=["sre"]).meaning) == set()
        )
        assert keys(
            ask(search, "certificate", where=EXPIRING, readers=["incident-response"]).meaning
        ) == {"INC-4830"}


def along(*weights: float) -> tuple[float, ...]:
    """A 2,560-value vector: these weights first, zeros after."""
    return tuple(weights) + (0.0,) * (2560 - len(weights))


class TestMeaning:
    """Spec 019, "How a search ranks" -- by meaning, nearest first by cosine distance."""

    def test_the_chunk_nearest_the_query_comes_first_whatever_its_id(self, sink, search):
        """The one where the ids sort `c-a`, `c-b`, `c-c`, and nearness puts `c-c` first."""
        write(sink, "INC-4830", "Certificate expired.", chunk_id="c-c", embedding=along(1, 0.1))
        write(
            sink, "INC-4821", "Card payments declined.", chunk_id="c-a", embedding=along(1, 1)
        )
        write(sink, "INC-4977", "WAL disk full.", chunk_id="c-b", embedding=along(0.1, 1))

        found = ask(search, "certificate", vector=along(1, 0))

        assert [candidate.chunk_id for candidate in found.meaning] == ["c-c", "c-a", "c-b"]


class TestWords:
    """Spec 019, "How a search ranks" -- by words, best first by `ts_rank_cd`."""

    def test_an_incident_key_is_found_by_its_words_and_ranked_by_how_densely_they_cover_it(
        self, sink, search
    ):
        """The one where `INC-4830` is named twice in its root cause and once in a follow-up.

        Ranked by `ts_rank_cd`, not by chunk id: the follow-up's id sorts
        first, and comes second. `INC-5102` never names it, and is not in the
        list; nor is `INC-4831`, a different key the words of which are close.
        """
        write(
            sink,
            "INC-4830",
            "INC-4830 root cause: renewal was automated, deployment was not. "
            "INC-4830 was declared at 09:12.",
            chunk_id="c-b-root-cause",
        )
        write(
            sink,
            "INC-4977",
            "A follow-up from INC-4830 on the WAL disk.",
            chunk_id="c-a-follow-up",
        )
        write(sink, "INC-5102", "orders-api ran out of memory.", chunk_id="c-c-oom")
        write(sink, "INC-4821", "Declined at checkout, as INC-4831 was.", chunk_id="c-d-near")

        found = ask(search, "INC-4830")

        assert [candidate.chunk_id for candidate in found.words] == [
            "c-b-root-cause",
            "c-a-follow-up",
        ]

    def test_a_query_no_chunk_matches_by_words_leaves_the_words_list_empty(self, sink, search):
        """The one where `kubernetes` matches no word, and the meaning list still holds one.

        A query of no words at all, or of punctuation only, is an empty
        `tsquery`: an empty list, not an error.
        """
        write(sink, "INC-4830", "The certificate expired at checkout.")

        kubernetes = ask(search, "kubernetes")

        assert kubernetes.words == ()
        assert keys(kubernetes.meaning) == {"INC-4830"}
        assert ask(search, "", vector=meaning("certificate")).words == ()
        assert ask(search, "!!!", vector=meaning("certificate")).words == ()


class TestDocuments:
    """`Lists.documents` -- every document either list holds, with its title and values."""

    def test_every_document_in_either_list_is_described_with_its_title_and_values(
        self, sink, search
    ):
        """The one where `INC-4830` is nearest, `OPS-114` has the words, and both are described.

        `candidates=1`, so each list holds one chunk, and each of a different
        document: `documents` describes the two.
        """
        root_cause = "The certificate expired at checkout."
        write(
            sink,
            "INC-4830",
            root_cause,
            title="INC-4830 Checkout TLS certificate expired",
            values=CARRIED["INC-4830"],
        )
        write(
            sink,
            "OPS-114",
            "Escalate to the on-call engineer within fifteen minutes.",
            source="procedures-confluence",
            acl=("sre",),
            title="OPS-114 Incident escalation procedure",
        )

        found = ask(search, "escalate", candidates=1, vector=meaning(root_cause))

        assert found.meaning == (
            Candidate(
                chunk_id="c-INC-4830",
                document_id="incidents-jira:INC-4830",
                kind="body",
                heading_path=("INC-4830 Checkout TLS certificate expired", "Summary"),
                text=root_cause,
            ),
        )
        assert keys(found.words) == {"OPS-114"}
        assert found.documents == {
            "incidents-jira:INC-4830": Described(
                document_id="incidents-jira:INC-4830",
                title="INC-4830 Checkout TLS certificate expired",
                values={"failure_category": "certificate-expiry", "component": "checkout"},
            ),
            "procedures-confluence:OPS-114": Described(
                document_id="procedures-confluence:OPS-114",
                title="OPS-114 Incident escalation procedure",
                values={},
            ),
        }


class TestModelsAndSnapshots:
    """What R19.6 and R19.7 compare: the models an index was embedded with, its snapshots."""

    def test_an_index_never_written_holds_no_model_no_snapshot_and_answers_nothing(
        self, dsn, schema, search
    ):
        """The one where no `dossier embed` has run: no schema, then tables and no rows.

        Empty, not an error: R19.6 refuses the search, naming what to run.
        """
        assert search.models(INDEX) == frozenset()
        assert search.snapshots(INDEX) == {}
        assert ask(search, "certificate") == Lists()

        with PostgresIndexSink(dsn, schema=schema) as sink:
            sink.prepare(INDEX, COLUMN)

        assert search.models(INDEX) == frozenset()
        assert search.snapshots(INDEX) == {}
        assert ask(search, "certificate") == Lists()

    def test_models_and_snapshots_are_read_for_the_index_asked_and_no_other(self, sink, search):
        """The one where `INC-4977` was embedded by another model, and `procedures` is apart."""
        other = "ollama:nomic-embed-text"
        write(sink, "INC-4830", "The certificate expired.", snapshot="a3f9c1e2")
        write(sink, "INC-4977", "The WAL disk filled.", snapshot="b7e2d4f0", model=other)
        write(
            sink,
            "OPS-114",
            "Escalate.",
            source="procedures-confluence",
            acl=("sre",),
            snapshot="c4d8e1a7",
            index="procedures",
        )

        assert search.models(INDEX) == frozenset({MODEL, other})
        assert search.snapshots(INDEX) == {
            "incidents-jira:INC-4830": "a3f9c1e2",
            "incidents-jira:INC-4977": "b7e2d4f0",
        }
        assert search.models("procedures") == frozenset({MODEL})
        assert search.snapshots("procedures") == {"procedures-confluence:OPS-114": "c4d8e1a7"}


class TestTies:
    """R19.1 -- two equal scores are ordered by chunk id, the same order on every machine."""

    def test_two_chunks_that_tie_are_ordered_by_their_ids_as_bytes(self, sink, search):
        """The one where two chunks say the same words, and `chunk-2` comes before `chunk1`.

        The same text is the same vector and the same text rank, so both lists
        tie. By bytes, as Python sorts them, `-` sorts before `1`. A database
        collating `en_US` ignores the hyphen and puts `chunk1` first: ordered by
        that, a list would depend on the server's locale. The tie holds at the
        cut too: one candidate is `chunk-2`.
        """
        text = "The certificate expired at checkout."
        write(sink, "INC-4830", text, chunk_id="chunk1")
        write(sink, "INC-4821", text, chunk_id="chunk-2")

        both = ask(search, "certificate", vector=meaning(text))
        one = ask(search, "certificate", vector=meaning(text), candidates=1)

        assert [candidate.chunk_id for candidate in both.meaning] == ["chunk-2", "chunk1"]
        assert [candidate.chunk_id for candidate in both.words] == ["chunk-2", "chunk1"]
        assert [candidate.chunk_id for candidate in one.meaning] == ["chunk-2"]
        assert [candidate.chunk_id for candidate in one.words] == ["chunk-2"]
