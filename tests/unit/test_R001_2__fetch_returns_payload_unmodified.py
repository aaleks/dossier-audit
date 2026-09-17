"""R1.2 — `fetch` returns the payload byte-for-byte as received.

Normalisation happens later, in the ledger layer, for hashing only. It never
changes what is stored.

Proved here for the `folder` connector. The JSON key-order row (example 1)
belongs to the Jira connector, which returns `response.content` verbatim
(`jira.py`); that row is not transcribed here yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.infrastructure.connectors.folder import FolderConnector

BOM_AND_CRLF = b"\xef\xbb\xbf# INC-4821\r\ntotal exposure CHF 48'200\r\n"


class TestFetchReturnsWhatWasThere:
    """R1.2 — a connector that tidies a payload changes every hash it touches."""

    def test_a_bom_and_crlf_endings_survive(self, tmp_path: Path):
        """Example 2: the one where 'helpful' normalisation would be a defect.

        Stripping a BOM or translating line endings would change the content hash
        of every file it touched, silently, and the stored snapshot would no
        longer be what was actually there.
        """
        (tmp_path / "INC-4821.md").write_bytes(BOM_AND_CRLF)

        assert FolderConnector(tmp_path).fetch("INC-4821.md").payload == BOM_AND_CRLF

    def test_a_zero_byte_payload_is_empty_bytes(self, tmp_path: Path):
        """Example 3: the one where an empty file is content, not an absence."""
        (tmp_path / "empty.md").write_bytes(b"")

        item = FolderConnector(tmp_path).fetch("empty.md")

        assert item.payload == b""
        assert item.payload is not None

    def test_bytes_that_are_not_valid_utf8_survive(self, tmp_path: Path):
        """The one where a PDF goes through untouched.

        A connector that decoded payloads would fail here rather than silently
        mangling them -- but the point is that it must do neither.
        """
        pdf = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nbinary \x00 payload\n"
        (tmp_path / "audit-note.pdf").write_bytes(pdf)

        assert FolderConnector(tmp_path).fetch("audit-note.pdf").payload == pdf

    def test_the_fetched_item_carries_its_key_and_media_type(self, tmp_path: Path):
        """The one where the caller does not have to guess what came back."""
        (tmp_path / "INC-4821.md").write_bytes(b"x")

        item = FolderConnector(tmp_path).fetch("INC-4821.md")

        assert item.key == "INC-4821.md"
        assert item.media_type == "text/markdown"

    def test_an_unknown_media_type_falls_back_rather_than_guessing(self, tmp_path: Path):
        """The one where an unrecognised extension is not invented."""
        (tmp_path / "notes.unknownext").write_bytes(b"x")

        item = FolderConnector(tmp_path).fetch("notes.unknownext")

        assert item.media_type == "application/octet-stream"

    def test_a_key_escaping_the_source_directory_is_refused(self, tmp_path: Path):
        """The one where a source configured to expose one folder exposes one folder.

        A key is data from a listing, and a listing is data from outside. R1.8
        keeps credentials out of config; this keeps a traversal from reading them
        off disk anyway.
        """
        (tmp_path / "inbox").mkdir()
        (tmp_path / ".env").write_bytes(b"JIRA_TOKEN=real-secret")

        with pytest.raises(ValueError):
            FolderConnector(tmp_path / "inbox").fetch("../.env")
