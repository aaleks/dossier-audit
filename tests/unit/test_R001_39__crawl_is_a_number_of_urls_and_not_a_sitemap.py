"""R1.39 — `crawl:` is a whole number of URLs, at least 1, and a source says
`crawl:` or `sitemap:`, never both.

`crawl:` is how many URLs a crawl may ask (R1.38), and there is no default: how
many pages a site has is its reader's to say. So `crawl: true` is not a switch
that turns crawling on, and a source listed by its sitemap and by its links at
once would be listed two ways. Each is refused when `sources.yaml` is loaded
(R1.10), before a request is sent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.docs_site import SITEMAP, URL

from dossier.config.load import ConfigError, load_sources
from dossier.infrastructure.connectors.web import WebKeys


def load(tmp_path: Path, *lines: str):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - id: vendor-docs\n"
        "    type: web\n"
        f"    url: {URL}\n" + "".join(f"    {line}\n" for line in lines),
        encoding="utf-8",
    )
    return load_sources(path, connectors={"web": WebKeys})


def refusal(tmp_path: Path, *lines: str) -> str:
    with pytest.raises(ConfigError) as error:
        load(tmp_path, *lines)
    return str(error.value)


class TestCrawlIsANumberOfUrlsAndNotASitemap:
    """R1.39 — `crawl:` is checked when `sources.yaml` is loaded."""

    def test_crawl_zero_is_refused(self, tmp_path: Path):
        """Example 1: the one where a crawl could ask nothing."""
        message = refusal(tmp_path, "crawl: 0")

        assert "vendor-docs" in message and "crawl" in message

    @pytest.mark.parametrize("crawl", ["true", "all", "2.5"])
    def test_crawl_that_is_not_a_whole_number_is_refused(self, tmp_path: Path, crawl: str):
        """Example 2: the one where `crawl:` is read as a switch."""
        message = refusal(tmp_path, f"crawl: {crawl}")

        assert "vendor-docs" in message and "crawl" in message

    def test_crawl_and_sitemap_together_are_refused(self, tmp_path: Path):
        """Example 3: the one where a source would be listed two ways."""
        message = refusal(tmp_path, "crawl: 50", f"sitemap: {SITEMAP}")

        assert "crawl" in message and "sitemap" in message

    def test_a_source_with_neither_is_listed_from_its_sitemap(self, tmp_path: Path):
        """Counter-example, row 4: the one R1.29 already describes."""
        (source,) = load(tmp_path)

        assert "crawl" not in source.options or source.options["crawl"] is None

    def test_a_whole_number_of_urls_is_taken(self, tmp_path: Path):
        """Row 3's other side: `crawl: 50` alone is a source listed by its links."""
        (source,) = load(tmp_path, "crawl: 50")

        assert source.options["crawl"] == 50
