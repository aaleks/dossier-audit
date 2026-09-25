"""R1.16 — a Confluence page is keyed by its id, and its marker is its version number.

A title changes when a page is renamed, and a key that changed would turn an
edit into a tombstone and a new item (R2.7). The marker is Confluence's own
version number, written `v37` so it reads as a page version beside a file's
`81920301:v2` (R1.18).

Every request goes through an `httpx.MockTransport` playing Confluence Data
Center. No socket is opened.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from dossier.domain.sync import needs_fetch
from dossier.infrastructure.connectors.confluence import ConfluenceConnector

BASE = "https://confluence.example.internal"
KEY = "81920114"


def listing(title: str, number: int, when: str = "2026-08-05T16:02:00.000Z"):
    """A Confluence whose search answers `OPS-114` under `title`, at `number`."""

    def handle(request: httpx.Request) -> httpx.Response:
        result = {
            "id": KEY,
            "type": "page",
            "status": "current",
            "title": title,
            "version": {"number": number, "when": when},
        }
        return httpx.Response(
            200,
            json={"results": [result], "start": 0, "limit": 50, "size": 1, "_links": {}},
        )

    return httpx.MockTransport(handle)


def listed(title: str, number: int):
    connector = ConfluenceConnector(
        base_url=BASE, query="space = OPS", transport=listing(title, number)
    )
    (ref,) = connector.list(None)
    return ref


class TestAConfluencePageIsKeyedByItsId:
    """R1.16 — the id is the address, and the version number is the marker."""

    def test_a_page_is_listed_under_its_id_at_its_version(self):
        """Example 1: the one where `OPS-114` is page `81920114` at version 37."""
        ref = listed("OPS-114 Incident escalation procedure", 37)

        assert ref.key == KEY
        assert ref.remote_version == "v37"
        assert ref.updated_at == datetime(2026, 8, 5, 16, 2, tzinfo=UTC)

    def test_an_edit_moves_the_marker_and_the_page_is_fetched_again(self):
        """Example 2: the one where `OPS-114` is edited to version 38."""
        ref = listed("OPS-114 Incident escalation procedure", 38)

        assert ref.remote_version == "v38"
        assert needs_fetch(recorded_version="v37", listed_version=ref.remote_version)

    def test_a_renamed_page_keeps_its_key(self):
        """Counter-example, row 3: the one where the title is not the address."""
        ref = listed("OPS-114 Escalation procedure (2026)", 38)

        assert ref.key == KEY
        assert ref.remote_version == "v38"
