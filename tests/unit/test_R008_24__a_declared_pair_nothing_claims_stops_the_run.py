"""R8.24 — a pair nothing claims stops the run only when the source declared its
kind.

R8.5's half that still holds. A kind written in `convert:` is a promise the
installation has to keep, and one it cannot keep is known before any work
starts: nothing converts, and every such document is named in one refusal.

A kind the source left to the default table is the other case (R8.25): nobody
asked for that file to be read, so it fails alone. Each rule carries the other
as its counter-example, because collapsing them one way stops an audit over one
attachment, and the other way turns a misconfigured pipeline into a pile of
per-document errors.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.application.convert import HeldDocument, convert_source
from dossier.domain.conversion import NoConverter, UnclaimedDefault
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.store import SnapshotStore

PAGE = b"<h1>PLAY-4001</h1><p>Duplicate payment retries</p>"
ALERTS = b'{"incident": "PLAY-4006", "alerts": []}'


class HtmlMarkdown:
    id = "html-markdown"
    version = "1.1.0"
    media_type = "text/html"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return payload


class PdfMarkdown:
    id = "pdf-markdown"
    version = "1.3.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return b"# extracted\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def held(store: SnapshotStore, payload: bytes, media_type: str) -> HeldDocument:
    return HeldDocument(snapshot=store.put(payload), media_type=media_type)


def exports(store: SnapshotStore) -> dict[str, HeldDocument]:
    return {
        "PLAY-4001-payment-retries.html": held(store, PAGE, "text/html"),
        "PLAY-4006-indexer-alerts.json": held(store, ALERTS, "application/json"),
    }


def convert(workspace: Path, documents, *, kinds, converters=None):
    return convert_source(
        source_id="incidents-exports",
        documents=documents,
        kinds=kinds,
        converters=list(converters if converters is not None else (HtmlMarkdown(),)),
        store=SnapshotStore(workspace),
        cache=ArtifactCache(workspace, namespace="convert"),
    )


class TestADeclaredPairNothingClaimsStopsEverything:
    """R8.24 — a source it was told to read one way, and cannot, is not half-read."""

    def test_a_declared_kind_nothing_claims_names_the_pair_and_the_way_out(
        self, workspace: Path
    ):
        """Row 1: the one where `page_images` was asked of a PDF nothing renders.

        Four things in the message, because someone hitting this has usually not
        installed a package: which document, what pair, what *is* claimed, and
        the entry point group that would fix it.
        """
        store = SnapshotStore(workspace)
        documents = {"OPS-114": held(store, b"%PDF-1.4\n", "application/pdf")}

        with pytest.raises(NoConverter) as error:
            convert(workspace, documents, kinds=["page_images"], converters=(PdfMarkdown(),))

        message = str(error.value)
        assert "OPS-114" in message
        assert "('application/pdf', 'page_images')" in message
        assert "(application/pdf, markdown)" in message, "the claimed pairs are listed"
        assert "dossier.converters" in message

    def test_markdown_declared_for_the_source_is_asked_of_the_json_too(self, workspace: Path):
        """Row 2: the one where `convert: [markdown]` covered every file.

        The source asked for markdown of everything it holds, so the JSON's pair
        was declared too, and it stops the run rather than failing alone.
        """
        store = SnapshotStore(workspace)

        with pytest.raises(NoConverter) as error:
            convert(workspace, exports(store), kinds=["markdown"])

        assert not isinstance(error.value, UnclaimedDefault)
        assert "PLAY-4006-indexer-alerts.json" in str(error.value)
        assert "('application/json', 'markdown')" in str(error.value)

    def test_nothing_is_written_not_even_the_page(self, workspace: Path):
        """Row 3: the one where the failure is total, like R4.1's.

        The exported page is perfectly convertible and is still not converted.
        The source is refused as a whole, so no artifact appears and nothing
        downstream sees a half-converted source.
        """
        store = SnapshotStore(workspace)

        with pytest.raises(NoConverter):
            convert(workspace, exports(store), kinds=["markdown"])

        cache = workspace / ".dossier" / "cache"
        assert not cache.exists() or not any(cache.rglob("*.*"))

    def test_every_unclaimed_document_is_named_not_just_the_first(self, workspace: Path):
        """The one where a mixed folder is diagnosed in a single run.

        Someone who pointed a pipeline at a directory of assorted files wants the
        list, not one example and another run to find the next.
        """
        store = SnapshotStore(workspace)
        documents = {
            "archive": held(store, b"PK\x03\x04", "application/zip"),
            "PLAY-4006-indexer-alerts.json": held(store, ALERTS, "application/json"),
        }

        with pytest.raises(NoConverter) as error:
            convert(workspace, documents, kinds=["markdown"])

        message = str(error.value)
        assert "archive" in message and "PLAY-4006-indexer-alerts.json" in message
        assert "2 document(s)" in message

    def test_a_default_kind_nothing_claims_does_not_stop_the_source(self, workspace: Path):
        """Counter-example (row 4): the one where nobody declared anything.

        The same two files from a source declaring no `convert:`. The JSON fails
        on its own and the page converts (R8.25).
        """
        store = SnapshotStore(workspace)

        report = convert(workspace, exports(store), kinds=None)

        assert report.present == ("PLAY-4001-payment-retries.html",)
        assert [failed.document for failed in report.failed] == [
            "PLAY-4006-indexer-alerts.json"
        ]

    def test_a_converter_that_fails_on_the_bytes_is_not_this_rule(self, workspace: Path):
        """The one where the configuration is right.

        A converter is registered for the declared pair and raises on the
        content. That is one bad document, not a misconfigured pipeline, and it
        must not stop the source (R8.6).
        """

        class Exploding(HtmlMarkdown):
            def convert(self, payload: bytes, options) -> bytes:
                raise ValueError("not decodable")

        store = SnapshotStore(workspace)
        documents = {"PLAY-4001-payment-retries.html": held(store, PAGE, "text/html")}

        report = convert(workspace, documents, kinds=["markdown"], converters=(Exploding(),))

        assert len(report.failed) == 1
        assert "not decodable" in report.failed[0].error
