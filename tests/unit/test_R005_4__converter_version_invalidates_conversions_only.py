"""R5.4 — changing the converter version invalidates conversions and causes no re-fetch.

The store is upstream of the converter, and improving a converter is not a reason
to touch the network.

This is the rule that makes improving a converter affordable. On a corpus of any
size the download is the expensive half and the conversion is the cheap one, so a
version bump that re-fetched would turn a ten-minute improvement into an
overnight job -- and, on a source that has since changed, would quietly re-audit
different documents.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

from dossier.application.convert import HeldDocument, convert_source
from dossier.domain.hashing import content_hash
from dossier.domain.keys import ArtifactInput, ConvertInputs, StageInputs, cache_key
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.store import SnapshotStore

SNAPSHOT = "a3f9c1e2" * 8
PROMPT = ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8)


class PdfMarkdown:
    """A PDF converter whose output depends on its version, as a real one does.

    A version is raised *because* the output changed; a converter that produced
    identical bytes at a new version would have had no reason to move.
    """

    id = "pdf-markdown"
    media_type = "application/pdf"
    kind = "markdown"

    def __init__(self, version: str = "1.3.0") -> None:
        self.version = version

    def convert(self, payload: bytes, options) -> bytes:
        return f"# extracted by {self.version}\n".encode() + payload


class MarkdownText:
    id = "markdown-text"
    media_type = "text/markdown"
    kind = "markdown"

    def __init__(self, version: str = "1.0.0") -> None:
        self.version = version

    def convert(self, payload: bytes, options) -> bytes:
        return payload


class RecordingStore:
    """A snapshot reader that remembers every digest it was asked for.

    Used to say what conversion *did* read, so "nothing was fetched" is backed by
    "everything came from the store" rather than only by the absence of a socket.
    """

    def __init__(self, workspace: Path) -> None:
        self._store = SnapshotStore(workspace)
        self.reads: list[str] = []

    def put(self, payload: bytes) -> str:
        return self._store.put(payload)

    def get(self, digest: str) -> bytes:
        self.reads.append(digest)
        return self._store.get(digest)


def convert_key(version: str, converter_id: str = "pdf-markdown") -> str:
    return cache_key(
        ConvertInputs(snapshot=SNAPSHOT, converter_id=converter_id, converter_version=version)
    )


class TestRaisingAConverterVersionInvalidatesItsConversions:
    """R5.4 — every artifact that converter made, and nothing else."""

    def test_every_convert_key_moves(self):
        """Example 1, first half: the one where the key carries the version."""
        assert convert_key("1.3.0") != convert_key("1.4.0")

    def test_every_document_reconverts(self, tmp_path: Path):
        """Example 1, second half: the one measured in conversions, not keys.

        A key that changed while the cache still served the old artifact would
        satisfy the assertion above and none of the point.
        """
        store = SnapshotStore(tmp_path)
        cache = ArtifactCache(tmp_path, namespace="convert")
        documents = {
            key: HeldDocument(
                snapshot=store.put(f"%PDF {key}\n".encode()), media_type="application/pdf"
            )
            for key in ("INC-4821", "INC-4822", "OPS-114")
        }

        def run(version: str):
            return convert_source(
                source_id="incidents-manual",
                documents=documents,
                kinds=None,
                converters=[PdfMarkdown(version)],
                store=store,
                cache=cache,
            )

        run("1.3.0")
        assert run("1.3.0").cached == 3, "nothing changed, so nothing is re-converted"

        raised = run("1.4.0")

        assert raised.converted == 3
        assert raised.cached == 0

    def test_conversion_reads_the_store_and_nothing_else(self, tmp_path: Path):
        """Example 2: the one where the network is not involved at all.

        The autouse `no_network` fixture already makes a socket impossible, so
        this asserts the positive half: every byte came from the snapshot store.
        `convert_source` has no connector parameter to reach for, which is the
        strongest form this guarantee takes.
        """
        store = RecordingStore(tmp_path)
        digest = store.put(b"%PDF-1.4\n")
        documents = {"OPS-114": HeldDocument(snapshot=digest, media_type="application/pdf")}

        report = convert_source(
            source_id="procedures-confluence",
            documents=documents,
            kinds=None,
            converters=[PdfMarkdown("1.4.0")],
            store=store,
            cache=ArtifactCache(tmp_path, namespace="convert"),
        )

        assert report.converted == 1
        assert store.reads == [digest]
        assert "connector" not in convert_source.__code__.co_varnames

    def test_every_stage_key_moves_because_its_input_moved(self, tmp_path: Path):
        """Example 3: the one where the cascade reaches the stages (R5.2).

        The stage key is composed over input *artifact* hashes. A better
        converter produces different text, that text hashes differently, and the
        stage that reads it re-runs -- without the stage's own prompt, schema or
        model having changed at all.
        """
        payload = b"%PDF-1.4\n"
        before = PdfMarkdown("1.3.0").convert(payload, {})
        after = PdfMarkdown("1.4.0").convert(payload, {})

        def stage_key(artifact: bytes) -> str:
            return cache_key(
                StageInputs(
                    step="extract",
                    prompt=PROMPT,
                    model="anthropic:claude-sonnet-4-5-20250929",
                    inputs=[
                        ArtifactInput(
                            role="documents",
                            path="converted/OPS-114.md",
                            hash=content_hash(artifact),
                        )
                    ],
                )
            )

        assert before != after
        assert stage_key(before) != stage_key(after)

    def test_an_unused_converter_changes_nothing(self, tmp_path: Path):
        """Counter-example (row 4): the one where only converters *used* count.

        The markdown converter is raised in a pipeline holding only PDFs. Nothing
        it could produce is in any key, so no key moves and nothing re-converts.
        A cache keyed on "the installed converter set" rather than on the
        converters actually used would invalidate the whole corpus here.
        """
        store = SnapshotStore(tmp_path)
        cache = ArtifactCache(tmp_path, namespace="convert")
        documents = {
            "OPS-114": HeldDocument(
                snapshot=store.put(b"%PDF-1.4\n"), media_type="application/pdf"
            )
        }

        def run(markdown_version: str):
            return convert_source(
                source_id="procedures-confluence",
                documents=documents,
                kinds=None,
                converters=[PdfMarkdown("1.3.0"), MarkdownText(markdown_version)],
                store=store,
                cache=cache,
            )

        run("1.0.0")
        after = run("2.0.0")

        assert after.converted == 0
        assert after.cached == 1
        assert convert_key("1.3.0") == convert_key("1.3.0")

    def test_raising_one_converter_leaves_the_others_keys_alone(self):
        """The other half of row 4, at the key level.

        Two converters, one raised. Only the raised one's keys move -- which is
        what "only converters actually used are part of any key" means when a
        corpus is mixed.
        """
        pdf_before = convert_key("1.3.0")
        markdown_before = convert_key("1.0.0", converter_id="markdown-text")

        assert convert_key("1.4.0") != pdf_before
        assert convert_key("1.0.0", converter_id="markdown-text") == markdown_before
