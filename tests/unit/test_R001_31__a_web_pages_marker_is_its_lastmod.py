"""R1.31 — a web page's marker is its sitemap `<lastmod>`, and `None` without one.

The marker is what R2.1 compares to decide whether to fetch. It is the string
the sitemap wrote, never parsed and never a fetch time (R1.5).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.docs_site import SITE, URL, DocsSite

from dossier.infrastructure.connectors.web import WebConnector


def refs(pages: dict[str, str | None]):
    connector = WebConnector(url=URL, transport=DocsSite(pages=pages).transport())
    return {ref.key: ref for ref in connector.list(None)}


class TestAWebPagesMarkerIsItsLastmod:
    """R1.31 — `<lastmod>` as written, or nothing."""

    def test_a_lastmod_with_a_time_is_the_marker(self):
        """Example 1: the one where `escalation` was modified at 16:02 UTC."""
        ref = refs({f"{SITE}/ops/escalation": "2026-08-05T16:02:00+00:00"})["escalation"]

        assert ref.remote_version == "2026-08-05T16:02:00+00:00"
        assert ref.updated_at == datetime(2026, 8, 5, 16, 2, tzinfo=UTC)

    def test_a_lastmod_that_is_a_date_alone_is_midnight_utc(self):
        """Example 2: the one where the index page gives only a date."""
        ref = refs({f"{SITE}/ops/": "2026-08-05"})["index"]

        assert ref.remote_version == "2026-08-05"
        assert ref.updated_at == datetime(2026, 8, 5, 0, 0, tzinfo=UTC)

    def test_a_fetch_carries_the_marker_the_listing_gave(self):
        """Example 3: the one where `fetch("escalation")` agrees with the listing."""
        site = DocsSite(pages={f"{SITE}/ops/escalation": "2026-08-05T16:02:00+00:00"})
        connector = WebConnector(url=URL, transport=site.transport())
        list(connector.list(None))

        assert connector.fetch("escalation").remote_version == "2026-08-05T16:02:00+00:00"

    def test_a_page_without_lastmod_has_no_marker(self):
        """Counter-example, row 4: the one where `dns-failover.html` names no `<lastmod>`."""
        ref = refs({f"{SITE}/ops/runbooks/dns-failover.html": None})[
            "runbooks/dns-failover.html"
        ]

        assert ref.remote_version is None
        assert ref.updated_at is None

    def test_a_lastmod_that_is_not_a_time_is_still_the_marker(self):
        """Counter-example, row 5: the one where the sitemap says `last week`."""
        ref = refs({f"{SITE}/ops/escalation": "last week"})["escalation"]

        assert ref.remote_version == "last week"
        assert ref.updated_at is None

    def test_a_lastmod_with_an_offset_is_read_at_that_offset(self):
        """Row 6: the one where the sitemap writes the time in Zurich's summer."""
        ref = refs({f"{SITE}/ops/escalation": "2026-08-05T18:02:00+02:00"})["escalation"]

        assert ref.remote_version == "2026-08-05T18:02:00+02:00"
        assert ref.updated_at == datetime(2026, 8, 5, 16, 2, tzinfo=UTC)

    def test_a_lastmod_written_before_its_loc_is_the_same_marker(self):
        """Row 7: the one where a `<url>` names its children in another order."""
        import httpx
        from tests.docs_site import SITEMAP

        served = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><lastmod>2026-08-05T16:02:00+00:00</lastmod>"
            f"<loc>{SITE}/ops/escalation</loc></url></urlset>"
        ).encode()
        site = DocsSite(responses={SITEMAP: httpx.Response(200, content=served)})
        (ref,) = WebConnector(url=URL, transport=site.transport()).list(None)

        assert ref.key == "escalation"
        assert ref.remote_version == "2026-08-05T16:02:00+00:00"
