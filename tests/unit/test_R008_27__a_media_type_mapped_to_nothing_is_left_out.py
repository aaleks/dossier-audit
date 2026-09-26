"""R8.27 — a media type `convert:` maps to `[]` is not read, and its documents
are reported as left out, not failed.

R8.25 made a file nothing converts fail on its own, and the cost was a source
exiting non-zero on every run over a file nobody wants read. Mapping its media
type to no kinds says so. The document is still held; it is not converted, no
step reads it, and it is counted apart from the failures so the choice stays
visible.

It is a declaration and never a default, and `convert: []` for a whole source
is still refused.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dossier.application.convert import HeldDocument, convert_source
from dossier.domain.conversion import NoConverter, is_read, used
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.store import SnapshotStore

JSON = "application/json"
LEAVE_JSON_OUT = {JSON: []}
PAGE = "PLAY-4001-payment-retries.html"
ALERTS = "PLAY-4006-indexer-alerts.json"


class HtmlMarkdown:
    id = "html-markdown"
    version = "1.1.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return payload


def _convert(workspace, *, kinds):
    store = SnapshotStore(workspace)
    documents = {
        PAGE: HeldDocument(snapshot=store.put(b"<h1>PLAY-4001</h1>"), media_type="text/html"),
        ALERTS: HeldDocument(snapshot=store.put(b'{"alerts": []}'), media_type=JSON),
    }
    return convert_source(
        source_id="incidents-exports",
        documents=documents,
        kinds=kinds,
        converters=[HtmlMarkdown()],
        store=store,
        cache=ArtifactCache(workspace, namespace="convert"),
    )


class TestAMediaTypeMappedToNothingIsLeftOut:
    """R8.27 — held, not read, and counted apart from the failures."""

    def test_the_json_is_left_out_and_nothing_fails(self, tmp_path):
        """Row 1: the one where the JSON is counted as left out.

        Held still counts it: the source holds three documents whatever it
        reads. It is not a failure and not present, so no step is asked about
        it (R6.15).
        """
        report = _convert(tmp_path, kinds=LEAVE_JSON_OUT)

        assert report.left_out == (ALERTS,)
        assert report.failed == ()
        assert report.held == 2
        assert report.converted == 1
        assert report.present == (PAGE,)

    def test_a_manifest_pins_nothing_for_it(self):
        """Row 2: the one where no converter read the JSON, so none is pinned (R8.9)."""
        pinned = used(
            requests=[("text/html", LEAVE_JSON_OUT), (JSON, LEAVE_JSON_OUT)],
            available=[HtmlMarkdown()],
        )

        assert [converter.id for converter in pinned] == ["html-markdown"]

    def test_a_source_that_did_not_say_so_still_fails_it(self, tmp_path):
        """Counter-example (row 3): the one where nobody left it out.

        Leaving a file out is something a source says. A new kind of attachment
        is reported the first time it arrives (R8.25).
        """
        report = _convert(tmp_path, kinds=None)

        assert report.left_out == ()
        assert [failed.document for failed in report.failed] == [ALERTS]

    def test_an_empty_list_for_a_whole_source_is_still_refused(self):
        """Counter-example (row 4): the one where `convert: []` reads nothing at all."""
        with pytest.raises(ValidationError, match="empty list"):
            SourceConfig(id="incidents-exports", type="folder", convert=[])

    def test_a_map_may_leave_a_media_type_out(self):
        """The one where the loader accepts what row 1 declares."""
        source = SourceConfig(id="incidents-exports", type="folder", convert=LEAVE_JSON_OUT)

        assert source.convert == {JSON: []}

    def test_a_plan_counts_only_what_a_run_reads(self):
        """The one where `--plan` and the run agree on the documents (R4.12).

        A type left out is read by nothing, and neither is a default pair
        nothing claims (R8.25). A declared pair nothing claims still raises: it
        stops the run, and the plan with it (R8.24).
        """
        html = [HtmlMarkdown()]

        assert is_read(media_type="text/html", kinds=LEAVE_JSON_OUT, available=html)
        assert not is_read(media_type=JSON, kinds=LEAVE_JSON_OUT, available=html)
        assert not is_read(media_type=JSON, kinds=None, available=html)
        with pytest.raises(NoConverter):
            is_read(media_type=JSON, kinds=["markdown"], available=html)
