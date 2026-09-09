"""R2.16 — the ledger records the media type its connector reported.

A snapshot's media type is whatever its connector said it was, recorded when the
payload was fetched. Nothing downstream re-derives it: a name on disk is not
evidence about content (R8.3), and conversion may not re-fetch to ask (R0.1).

Without this the convert use case has no way to choose a converter, which is
exactly how the rule was found -- R8.5 and R8.6 could be proved as unit rules
only by passing media types in, and the CLI had nowhere to get them from.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dossier.application.sync import sync_source
from dossier.domain.pipeline import SourceConfig
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.store import SnapshotStore

NOW = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


class StubConnector:
    """A connector that reports exactly the media type it is told to."""

    def __init__(self, items: dict[str, tuple[bytes, str, str | None]]) -> None:
        self._items = items
        self.fetched: list[str] = []

    def list(self, since=None) -> Iterator[ItemRef]:
        for key in sorted(self._items):
            _, _, version = self._items[key]
            yield ItemRef(key=key, remote_version=version)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        payload, media_type, version = self._items[key]
        return RawItem(
            key=key, payload=payload, media_type=media_type, remote_version=version
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


def sync(workspace: Path, connector: StubConnector, *, now: datetime = NOW):
    with Ledger(workspace) as ledger:
        report = sync_source(
            config=SourceConfig(id="incidents-manual", type="stub"),
            connector=connector,
            store=SnapshotStore(workspace),
            ledger=ledger,
            now=now,
        )
    return report


def rows(workspace: Path) -> dict[str, str]:
    with Ledger(workspace) as ledger:
        return {row.key: row.media_type for row in ledger.rows("incidents-manual")}


class TestTheLedgerRemembersTheMediaType:
    """R2.16 — recorded once, by the only component that saw the source."""

    def test_a_fetched_item_records_what_its_connector_said(self, tmp_path: Path):
        """Example 1: the one where a folder source reports `text/markdown`."""
        connector = StubConnector(
            {"INC-4821": (b"# INC-4821\n", "text/markdown", None)}
        )

        sync(tmp_path, connector)

        assert rows(tmp_path) == {"INC-4821": "text/markdown"}

    def test_an_unfetched_item_keeps_the_type_it_had(self, tmp_path: Path):
        """Example 2: the one where a version marker skips the fetch (R2.15).

        Nothing re-derives the type on a run that never opened the payload. If
        this cleared it, every incremental sync would quietly strip the one fact
        conversion depends on.
        """
        connector = StubConnector(
            {"OPS-114": (b"%PDF-1.4\n", "application/pdf", "v37")}
        )
        sync(tmp_path, connector)
        connector.fetched.clear()

        sync(tmp_path, connector, now=LATER)

        assert connector.fetched == [], "the marker is unchanged, so nothing is read"
        assert rows(tmp_path) == {"OPS-114": "application/pdf"}

    def test_a_pdf_export_records_the_pdf_type(self, tmp_path: Path):
        """Example 3: the one where the key says nothing about the bytes.

        `OPS-114` is a Confluence page exported as a PDF. Its key carries no
        extension at all, so a reader deriving the type from the key would have
        nothing to work with.
        """
        connector = StubConnector({"OPS-114": (b"%PDF-1.4\n", "application/pdf", "v37")})

        sync(tmp_path, connector)

        assert rows(tmp_path) == {"OPS-114": "application/pdf"}

    def test_the_connectors_answer_wins_over_the_name(self, tmp_path: Path):
        """Counter-example (row 4): the one named `.pdf` that is markdown.

        The connector saw the source and said `text/markdown`. That is the
        record. Anything downstream re-deriving from the key would pick
        `application/pdf`, hand markdown to a PDF parser, and fail a long way
        from the cause (R8.3 example 4).
        """
        connector = StubConnector({"notes.pdf": (b"# not a pdf\n", "text/markdown", None)})

        sync(tmp_path, connector)

        assert rows(tmp_path) == {"notes.pdf": "text/markdown"}

    def test_a_changed_payload_records_the_new_type(self, tmp_path: Path):
        """The one where a source starts exporting something else.

        A Confluence space switched from PDF export to markdown is a real
        migration, and the ledger has to follow it rather than keeping the type
        it first saw.
        """
        connector = StubConnector({"OPS-114": (b"%PDF-1.4\n", "application/pdf", "v37")})
        sync(tmp_path, connector)

        moved = StubConnector({"OPS-114": (b"# OPS-114\n", "text/markdown", "v38")})
        sync(tmp_path, moved, now=LATER)

        assert rows(tmp_path) == {"OPS-114": "text/markdown"}

    def test_the_media_type_is_part_of_what_two_syncs_must_agree_on(self, tmp_path: Path):
        """The one that keeps R2.9 honest about the new column.

        `content()` is what R2.9 compares. A field left out of it would be a
        field two syncs could disagree on without anything noticing.
        """
        connector = StubConnector({"INC-4821": (b"# INC-4821\n", "text/markdown", None)})
        sync(tmp_path, connector)
        with Ledger(tmp_path) as ledger:
            before = [row.content() for row in ledger.rows("incidents-manual")]

        sync(tmp_path, connector, now=LATER)
        with Ledger(tmp_path) as ledger:
            after = [row.content() for row in ledger.rows("incidents-manual")]

        assert before == after
        assert any("text/markdown" in str(entry) for entry in before), (
            "the media type must be inside what R2.9 compares"
        )


@pytest.mark.parametrize(
    "media_type", ["text/markdown", "application/pdf", "application/octet-stream"]
)
def test_any_media_type_a_connector_reports_survives_a_round_trip(
    tmp_path: Path, media_type: str
):
    """The one where the ledger does not interpret what it stores.

    `application/octet-stream` is the folder connector's answer when it cannot
    guess. Storing it verbatim is what lets R8.5 report an unclaimed type rather
    than the ledger silently substituting something plausible.
    """
    connector = StubConnector({"item": (b"bytes", media_type, None)})

    sync(tmp_path, connector)

    assert rows(tmp_path) == {"item": media_type}


class TestTheConnectorsAnswerDoesNotDependOnTheMachine:
    """R2.16 — the guess is made once, and it is the same guess everywhere.

    The rule permits a connector to guess from a filename, because a folder
    source has nothing else. It does not permit the guess to differ by host --
    that answer is recorded, picks the converter (R8.3), and the converter's id
    and version reach every cache key above it (R0.4, R5.6).

    Found by `/quality`: the folder connector used `mimetypes.guess_type`, which
    is seeded from `/etc/mime.types` on Linux and `HKEY_CLASSES_ROOT` on Windows.
    On the machine this was found on, `.csv` answered `application/vnd.ms-excel`.
    """

    def test_the_table_is_ours_and_not_the_hosts(self):
        """The one where the two answers are shown to differ.

        `mimetypes` is consulted here only to demonstrate that it disagrees with
        us -- it is the evidence, not the expectation. If a future Python or a
        future host happens to agree, the assertion below still holds because it
        names our answer.
        """
        import mimetypes

        from dossier.domain.conversion import media_type_for

        assert media_type_for("figures.csv") == "text/csv"
        host = mimetypes.guess_type("figures.csv")[0]
        if host != "text/csv":
            assert media_type_for("figures.csv") != host, (
                "the host disagrees, and we do not follow it"
            )

    def test_an_unregistered_extension_gets_an_honest_answer(self):
        """The one where guessing would be worse than admitting ignorance.

        `application/octet-stream` says "bytes", which is true of anything. R8.5
        then refuses it by name and tells the user which converter to install --
        a plausible guess would instead hand the file to a converter never meant
        to read it.
        """
        from dossier.domain.conversion import media_type_for

        assert media_type_for("archive.zip") == "application/octet-stream"
        assert media_type_for("no-extension") == "application/octet-stream"

    def test_the_extension_is_matched_without_case(self):
        """The one where a filesystem preserved a case nobody chose."""
        from dossier.domain.conversion import media_type_for

        assert media_type_for("INC-4821.MD") == media_type_for("inc-4821.md")

    def test_a_dotted_name_uses_its_last_extension(self):
        """The one where the name has more dots than extensions."""
        from dossier.domain.conversion import media_type_for

        assert media_type_for("incident.2026.07.28.md") == "text/markdown"

    def test_the_folder_connector_reports_what_the_table_says(self, tmp_path: Path):
        """The one that checks the connector actually uses it.

        A pure table nothing consults would pass every row above.
        """
        from dossier.infrastructure.connectors.folder import FolderConnector

        root = tmp_path / "inbox"
        root.mkdir()
        (root / "figures.csv").write_bytes(b"a,b\n1,2\n")

        assert FolderConnector(root).fetch("figures.csv").media_type == "text/csv"
