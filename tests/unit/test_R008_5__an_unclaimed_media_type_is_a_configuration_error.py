"""R8.5 — a media type no converter claims stops the run, naming the type and how
to add one.

Reported before any conversion starts. A pipeline pointed at bytes it cannot read
is misconfigured, and the fix is an installation rather than a retry.

This rule and R8.6 look alike and behave differently on purpose, which is why
each has its own counter-example pointing at the other. Collapsing them one way
turns an installation problem into nine mysterious per-document errors; the other
way turns one corrupt PDF into a run that produced nothing at all.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.application.convert import HeldDocument, convert_source
from dossier.domain.conversion import NoConverter
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.store import SnapshotStore

MARKDOWN = b"# INC-4821\n\nTotal exposure CHF 48'200 on page 3.\n"


class Markdown:
    id = "markdown-text"
    version = "1.0.0"
    media_type = "text/markdown"
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


def convert(workspace: Path, documents, *, kinds=None, converters=None):
    return convert_source(
        source_id="incidents-manual",
        documents=documents,
        kinds=kinds,
        converters=list(converters if converters is not None else (Markdown(),)),
        store=SnapshotStore(workspace),
        cache=ArtifactCache(workspace, namespace="convert"),
    )


class TestAnUnclaimedMediaTypeStopsEverything:
    """R8.5 — a source it cannot read is a source it does not half-read."""

    def test_the_error_names_the_document_the_type_and_the_way_out(self, workspace: Path):
        """Example 1: the one where a `.zip` lands in a watched folder.

        Four things in the message, because someone hitting this has usually not
        installed a package: which document, what it is, what *is* claimed, and
        the entry point group that would fix it.
        """
        store = SnapshotStore(workspace)
        documents = {
            "INC-4821": held(store, MARKDOWN, "text/markdown"),
            "archive": held(store, b"PK\x03\x04", "application/zip"),
        }

        with pytest.raises(NoConverter) as error:
            convert(workspace, documents)

        message = str(error.value)
        assert "archive" in message
        assert "application/zip" in message
        assert "text/markdown" in message, "the claimed pairs are listed"
        assert "dossier.converters" in message

    def test_nothing_is_written_and_no_document_is_converted(self, workspace: Path):
        """Example 2: the one where the failure is total, like R4.1's.

        `INC-4821` is perfectly convertible and is still not converted. The
        source is refused as a whole, so no artifact appears and nothing
        downstream sees a half-converted source.
        """
        store = SnapshotStore(workspace)
        documents = {
            "INC-4821": held(store, MARKDOWN, "text/markdown"),
            "archive": held(store, b"PK\x03\x04", "application/zip"),
        }

        with pytest.raises(NoConverter):
            convert(workspace, documents)

        cache = workspace / ".dossier" / "cache"
        assert not cache.exists() or not any(cache.rglob("*.*"))

    def test_a_claimed_media_type_with_an_unclaimed_kind_is_the_same_error(
        self, workspace: Path
    ):
        """Example 3: the one where only half the pair is registered.

        `application/pdf` is claimed, for `markdown`. A source asking for
        `page_images` is asking for a pair nobody registered, and the fact that
        the media type is familiar makes it more confusing, not less.
        """
        store = SnapshotStore(workspace)
        documents = {"OPS-114": held(store, b"%PDF-1.4\n", "application/pdf")}

        with pytest.raises(NoConverter) as error:
            convert(workspace, documents, kinds=["page_images"], converters=(PdfMarkdown(),))

        assert "page_images" in str(error.value)

    def test_every_unclaimed_document_is_named_not_just_the_first(self, workspace: Path):
        """The one where a mixed folder is diagnosed in a single run.

        Someone who pointed a pipeline at a directory of assorted files wants the
        list, not one example and another run to find the next.
        """
        store = SnapshotStore(workspace)
        documents = {
            "archive": held(store, b"PK\x03\x04", "application/zip"),
            "photo": held(store, b"\xff\xd8\xff", "image/jpeg"),
        }

        with pytest.raises(NoConverter) as error:
            convert(workspace, documents)

        message = str(error.value)
        assert "archive" in message and "photo" in message
        assert "2 document(s)" in message

    def test_a_converter_that_fails_on_the_bytes_is_not_this_rule(self, workspace: Path):
        """Counter-example (row 4): the one where the configuration is right.

        A converter is registered for the pair and raises on the content. That is
        one bad document, not a misconfigured pipeline, and it must not stop the
        source (R8.6). Asserting it here keeps the two rules from being
        implemented as one.
        """
        class Exploding:
            id = "markdown-text"
            version = "1.0.0"
            media_type = "text/markdown"
            kind = "markdown"

            def convert(self, payload: bytes, options) -> bytes:
                raise ValueError("not decodable")

        store = SnapshotStore(workspace)
        documents = {"INC-4821": held(store, MARKDOWN, "text/markdown")}

        report = convert(workspace, documents, converters=(Exploding(),))

        assert len(report.failed) == 1
        assert "not decodable" in report.failed[0].error
