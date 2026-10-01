"""R18.8 — a document's record comes from the pipeline's latest run, and only when
that run read the snapshot the ledger holds now.

A run's answers describe the snapshot it read. Attached to a newer one, they
would describe text that is no longer there, so a record is carried only when
the run read what the index is about to hold, and every other case is named.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from dossier.domain.index import LatestRun, record_for
from dossier.domain.schemas import FieldRecord

RUN = "20260925T091500Z-5e6f"
HELD = "a3f9c1e2" * 8
EARLIER = "77c1b40a" * 8
ANSWER = (FieldRecord(field="failure_category", value="certificate-expiry"),)


def latest(**overrides) -> LatestRun:
    values = {
        "run_id": RUN,
        "pinned": {"INC-4830": HELD, "INC-4822": HELD},
        "failed": {"INC-4822": "extract"},
        "records": {"INC-4830": ANSWER},
    }
    return LatestRun(**(values | overrides))


class TestARecordComesFromTheRunThatReadTheHeldSnapshot:
    """R18.8 — the latest run's record, of the snapshot held, or a reason why not."""

    def test_a_run_that_read_the_held_snapshot_carries_its_record(self):
        """Row 1 — the one where `20260925T091500Z-5e6f` read `INC-4830` as it is held."""
        assert record_for("INC-4830", held_snapshot=HELD, run=latest()) == (ANSWER, None)

    def test_a_record_of_an_earlier_snapshot_is_stale(self):
        """Row 2, counter-example — the one re-synced since the run read it."""
        assert record_for(
            "INC-4830", held_snapshot=HELD, run=latest(pinned={"INC-4830": EARLIER})
        ) == (
            None,
            f"INC-4830: record stale: {RUN} read an earlier snapshot",
        )

    def test_a_document_the_run_failed_has_no_record(self):
        """Row 3, counter-example — the one `extract` failed (R4.27)."""
        assert record_for("INC-4822", held_snapshot=HELD, run=latest()) == (
            None,
            f"INC-4822: no record: failed at extract in {RUN}",
        )

    def test_with_no_run_there_is_no_record_and_nothing_per_document(self):
        """Row 4, counter-example — the one where `incident-audit` has never run.

        The one line saying so is the command's, once, not one per document.
        """
        from tests.fakes import FakeEmbeddingProvider, FakeIndexSink
        from tests.unit.test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss import (
            declaration,
        )

        from dossier.application.embed import ToIndex, embed_index
        from dossier.domain.chunks import HeadingsChunker
        from dossier.domain.index import IndexFields
        from dossier.infrastructure.cache import ArtifactCache

        assert record_for("INC-4830", held_snapshot=HELD, run=None) == (None, None)
        with TemporaryDirectory() as cache:
            report = embed_index(
                declaration=declaration().model_copy(
                    update={"fields": IndexFields(filter=("failure_category",))}
                ),
                documents=[
                    ToIndex("incidents-jira", key, HELD, f"# {key}\n\nText.\n")
                    for key in ("INC-4830", "INC-4822")
                ],
                readers={"incidents-jira": ("incident-response",)},
                chunker=HeadingsChunker(max_chars=2000),
                embedder=FakeEmbeddingProvider(),
                vectors=ArtifactCache(Path(cache), namespace="embed"),
                sink=FakeIndexSink(),
                run=None,
            )
        assert report.notes == ("no run of incident-audit yet",)

    def test_a_document_synced_after_the_run_has_no_record_of_it(self):
        """Row 5, counter-example — the one where `INC-4901` arrived after the run."""
        assert record_for("INC-4901", held_snapshot=HELD, run=latest()) == (
            None,
            f"INC-4901: no record: {RUN} did not read it",
        )

    def test_a_run_that_filed_no_answer_says_so(self):
        """Row 6, counter-example — the one the run read and answered nothing about."""
        run = latest(pinned={"INC-4901": HELD}, failed={}, records={})

        assert record_for("INC-4901", held_snapshot=HELD, run=run) == (
            None,
            f"INC-4901: no record: {RUN} filed no answer for it",
        )
