"""R1.24 — a web page is keyed by its URL relative to the source's `url`, with `index`
for a directory.

A key is also a file name under `runs/` (R0.11), and `runbooks/` is not one. The
decision is pure, and lives in `dossier.domain.web`.
"""

from __future__ import annotations

import pytest

from dossier.domain.web import SitemapPage, in_scope, listing, page_key, prefix

SITE = "https://docs.example.org"
SCOPE = prefix(f"{SITE}/ops/")


def everything(url: str) -> bool:
    return True


class TestAWebPageIsKeyedByItsRelativeUrl:
    """R1.24 — relative to `url`, and a directory is `index`."""

    @pytest.mark.parametrize(
        ("url", "key"),
        [
            (f"{SITE}/ops/escalation", "escalation"),
            (f"{SITE}/ops/runbooks/dns-failover.html", "runbooks/dns-failover.html"),
            (f"{SITE}/ops/", "index"),
            (f"{SITE}/ops/runbooks/", "runbooks/index"),
        ],
        ids=["page", "nested", "the-prefix-itself", "a-directory"],
    )
    def test_a_page_is_keyed_relative_to_the_prefix(self, url: str, key: str):
        """Examples 1-4: the one where a page is its path, and a directory `index`."""
        assert page_key(url, SCOPE) == key

    def test_a_url_without_its_slash_is_the_same_scope(self):
        """Example 5: the one where `url: …/ops` is written without the slash."""
        scope = prefix(f"{SITE}/ops")

        assert scope == SCOPE
        assert page_key(f"{SITE}/ops/escalation", scope) == "escalation"
        assert page_key(f"{SITE}/ops", scope) == "index"
        assert in_scope(f"{SITE}/ops", scope)
        assert not in_scope(f"{SITE}/opsx/guide", scope)

    def test_a_fragment_is_not_part_of_the_key(self):
        """Counter-example, row 6: the one where `#contacts` is a place on a page."""
        assert page_key(f"{SITE}/ops/escalation#contacts", SCOPE) == "escalation"

    def test_a_fragment_does_not_make_a_second_page(self):
        """Counter-example, row 6: the one where the sitemap names both spellings."""
        listed = listing(
            [
                SitemapPage(loc=f"{SITE}/ops/escalation", lastmod="2026-08-05"),
                SitemapPage(loc=f"{SITE}/ops/escalation#contacts", lastmod=None),
            ],
            SCOPE,
            allowed=everything,
        )

        assert list(listed.pages) == ["escalation"]
        assert listed.pages["escalation"].url == f"{SITE}/ops/escalation"

    def test_two_urls_claiming_one_key_fail_the_listing(self):
        """Counter-example, row 7: the one where `runbooks/` and `runbooks/index` collide."""
        with pytest.raises(ValueError) as raised:
            listing(
                [
                    SitemapPage(loc=f"{SITE}/ops/runbooks/", lastmod=None),
                    SitemapPage(loc=f"{SITE}/ops/runbooks/index", lastmod=None),
                ],
                SCOPE,
                allowed=everything,
            )

        message = str(raised.value)
        assert f"{SITE}/ops/runbooks/" in message
        assert f"{SITE}/ops/runbooks/index" in message
        assert "'runbooks/index'" in message
