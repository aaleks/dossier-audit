"""R1.36 — a web source starts each request to its site at least the longer of its
`delay:` and the site's `Crawl-delay` after the one before.

The site's pace is a floor a source may raise and never lower. With neither,
requests go back to back, as they always have. Time here is a clock the test
holds: a wait is recorded, and no test sleeps.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from tests.docs_site import HTML, ROBOTS, SITE, URL, DocsSite

from dossier.config.load import ConfigError, load_sources
from dossier.domain.web import spacing
from dossier.infrastructure.connectors.web import WebConnector, WebKeys

ESCALATION = f"{SITE}/ops/escalation"


class Clock:
    """Seconds that pass only when the connector waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def crawl_delay(seconds: int) -> httpx.Response:
    return httpx.Response(200, text=f"User-agent: *\nCrawl-delay: {seconds}\n")


def waits(site: DocsSite, *, delay: float | None = None) -> list[float]:
    """The waits before each request of a first `fetch("escalation")`."""
    clock = Clock()
    connector = WebConnector(
        url=URL, delay=delay, transport=site.transport(), sleep=clock.sleep, clock=clock
    )
    connector.fetch("escalation")
    return clock.waits


class TestAWebSourceSpacesItsRequests:
    """R1.36 — the longer of `delay:` and `Crawl-delay`, between every two requests."""

    def test_delay_spaces_every_request_after_the_first(self):
        """Example 1: the one where `delay: 2` puts two seconds between each."""
        site = DocsSite()

        assert waits(site, delay=2) == [2.0, 2.0]
        assert site.urls_asked()[0] == ROBOTS
        assert site.urls_asked()[-1] == ESCALATION

    def test_crawl_delay_spaces_them_from_the_sitemap_on(self):
        """Example 2: the one where the site asks for five seconds."""
        site = DocsSite(responses={ROBOTS: crawl_delay(5)})

        assert waits(site) == [5.0, 5.0]

    def test_a_source_asks_no_faster_than_its_site_asks(self):
        """Example 3: the one where `Crawl-delay: 5` outlasts `delay: 2`."""
        site = DocsSite(responses={ROBOTS: crawl_delay(5)})

        assert waits(site, delay=2) == [5.0, 5.0]

    def test_a_source_may_ask_more_slowly_than_its_site_asks(self):
        """Example 4: the one where `delay: 10` outlasts `Crawl-delay: 5`."""
        site = DocsSite(responses={ROBOTS: crawl_delay(5)})

        assert waits(site, delay=10) == [10.0, 10.0]

    def test_a_redirect_hop_waits_like_any_request(self):
        """Example 5: the one where `escalation` moves to `escalation/`."""
        site = DocsSite(
            responses={
                ESCALATION: httpx.Response(301, headers={"Location": f"{ESCALATION}/"}),
                f"{ESCALATION}/": httpx.Response(
                    200, headers={"Content-Type": HTML}, content=b"<h1>Escalation</h1>"
                ),
            }
        )

        assert waits(site, delay=2) == [2.0, 2.0, 2.0]
        assert site.urls_asked()[-2:] == [ESCALATION, f"{ESCALATION}/"]

    def test_with_neither_requests_go_back_to_back(self):
        """Counter-example, row 6: the one with no pace at all."""
        site = DocsSite()

        assert waits(site) == []
        assert len(site.urls_asked()) == 3

    @pytest.mark.parametrize("delay", ["-1", "soon"])
    def test_a_delay_that_is_not_a_wait_is_refused_at_load(self, tmp_path: Path, delay: str):
        """Counter-example, row 7: the one where `delay:` cannot be waited for."""
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - id: vendor-docs\n"
            "    type: web\n"
            f"    url: {URL}\n"
            f"    delay: {delay}\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"web": WebKeys})

        assert "vendor-docs" in str(error.value) and "delay" in str(error.value)


class TestSpacingIsTheLongerOfTheTwo:
    """R1.36 — the decision, apart from the waiting."""

    @pytest.mark.parametrize(
        ("delay", "crawl", "expected"),
        [(2, None, 2), (None, 5, 5), (2, 5, 5), (10, 5, 10), (None, None, 0)],
    )
    def test_the_longer_stands(self, delay, crawl, expected):
        """Rows 1 to 4 and 6, as the one number the connector waits by."""
        assert spacing(delay, crawl) == expected
