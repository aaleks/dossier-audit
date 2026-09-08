"""R8.6 — a conversion failure is isolated to its own document.

The other documents convert, the stages run over them, and the run says which
document failed and why.

An audit over nine of ten documents is useful; an audit that quietly covered nine
and said ten is not. That distinction is the whole rule, and it is why the report
carries each failure's own reason rather than a count.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.application.convert import HeldDocument, convert_source
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.store import SnapshotStore

# `INC-5044` is the kafka-consumer-stall one-pager in the PDF corpus, and the
# document R8.6's example table truncates.
CORRUPT = "INC-5044"
TEN = [
    "INC-4821", "INC-4822", "INC-4901", "INC-5044", "INC-5102",
    "INC-5230", "INC-5310", "INC-5388", "INC-5401", "INC-5455",
]


class Fussy:
    """A converter that refuses one exact payload, as a truncated file would."""

    id = "markdown-text"
    version = "1.0.0"
    media_type = "text/markdown"
    kind = "markdown"

    def __init__(self, refuse: bytes = b"") -> None:
        self._refuse = refuse
        self.calls: list[bytes] = []

    def convert(self, payload: bytes, options) -> bytes:
        self.calls.append(payload)
        if payload == self._refuse:
            raise ValueError("unexpected end of file")
        return payload


def documents(store: SnapshotStore, corrupt: str | None = CORRUPT) -> dict[str, HeldDocument]:
    """Ten documents, one of which is truncated."""
    held = {}
    for key in TEN:
        payload = b"" if key == corrupt else f"# {key}\n\nbody\n".encode()
        held[key] = HeldDocument(snapshot=store.put(payload), media_type="text/markdown")
    return held


def convert(workspace: Path, held, converter):
    return convert_source(
        source_id="incidents-manual",
        documents=held,
        kinds=None,
        converters=[converter],
        store=SnapshotStore(workspace),
        cache=ArtifactCache(workspace, namespace="convert"),
    )


class TestOneBadDocumentIsOneBadDocument:
    """R8.6 — the other nine are unaffected and the run says which failed."""

    def test_nine_convert_and_the_tenth_is_reported(self, tmp_path: Path):
        """Example 1: the one where `INC-5044` is truncated."""
        store = SnapshotStore(tmp_path)
        held = documents(store)

        report = convert(tmp_path, held, Fussy(refuse=b""))

        assert report.converted == 9
        assert [failure.document for failure in report.failed] == [CORRUPT]
        assert "unexpected end of file" in report.failed[0].error

    def test_the_nine_are_what_the_stages_read(self, tmp_path: Path):
        """Example 2: the one where the failed document is absent, not empty.

        An empty string would let a stage audit a blank page and find nothing
        wrong with it. Absence is what makes the gap visible (R6.9).
        """
        store = SnapshotStore(tmp_path)

        report = convert(tmp_path, documents(store), Fussy(refuse=b""))

        assert len(report.text) == 9
        assert CORRUPT not in report.text
        assert report.text["INC-4821"].startswith("# INC-4821")

    def test_a_repeat_run_converts_only_the_repaired_document(self, tmp_path: Path):
        """Example 3: the one where the nine are already paid for.

        The failed document was never cached -- there was no artifact to cache --
        so repairing it costs exactly one conversion. Asserting on the
        converter's own call list rather than on the counts, because "only one
        converted" and "only one was *asked* to convert" are different claims and
        this rule needs the second.
        """
        store = SnapshotStore(tmp_path)
        convert(tmp_path, documents(store), Fussy(refuse=b""))

        repaired = documents(store, corrupt=None)
        watcher = Fussy(refuse=b"never matches")
        report = convert(tmp_path, repaired, watcher)

        assert report.converted == 1
        assert report.cached == 9
        assert len(watcher.calls) == 1, "the nine cache hits never reached the converter"

    def test_every_document_failing_is_still_ten_reasons(self, tmp_path: Path):
        """Counter-example (row 4): the one where collapsing would lose the evidence.

        A single "the source failed" would be shorter and would hide which
        document failed how. Ten failures are ten pieces of evidence.
        """
        store = SnapshotStore(tmp_path)

        class AlwaysFails(Fussy):
            def convert(self, payload: bytes, options) -> bytes:
                raise ValueError(f"cannot read {len(payload)} bytes")

        report = convert(tmp_path, documents(store, corrupt=None), AlwaysFails())

        assert [failure.document for failure in report.failed] == TEN
        assert report.converted == 0
        assert all(failure.error for failure in report.failed), (
            "every failure carries its own reason, not a shared summary"
        )

    def test_a_failure_writes_no_artifact_for_that_document(self, tmp_path: Path):
        """The one where a failed conversion leaves nothing behind.

        A cache entry for a document that failed would be served on the next run,
        turning a transient failure into a permanent wrong answer (R5.8's shape).
        """
        store = SnapshotStore(tmp_path)
        held = documents(store)

        report = convert(tmp_path, held, Fussy(refuse=b""))

        cache = ArtifactCache(tmp_path, namespace="convert")
        for failure in report.failed:
            assert failure.artifacts == ()
        assert cache.get("0" * 64) is None, "sanity: an unknown key is a miss"

    @pytest.mark.parametrize("raised", [ValueError, KeyError, RuntimeError, TypeError])
    def test_any_exception_a_converter_raises_is_contained(self, tmp_path: Path, raised):
        """The one where a third-party converter raises something unforeseen.

        A converter is someone else's package (R8.7). It may raise anything at
        all, and none of it should take the other nine documents down.
        """
        store = SnapshotStore(tmp_path)

        class Raising(Fussy):
            def convert(self, payload: bytes, options) -> bytes:
                if payload == b"":
                    raise raised("boom")
                return payload

        report = convert(tmp_path, documents(store), Raising())

        assert report.converted == 9
        assert [failure.document for failure in report.failed] == [CORRUPT]
        assert raised.__name__ in report.failed[0].error
