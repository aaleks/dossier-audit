"""R1.42 — `render:` is `browser` or absent, and a browser that is not installed is
named, never fetched.

`render: browser` is one way to draw a page, named, so `render: true` is not a
switch that turns it on. Playwright is the extra `dossier[browser]`: a source
that asks for a browser on a machine without it is refused when its connector
is built, before a request is sent, and the error names the extra. A missing
Chromium is `tests/integration/test_R001_42__…`'s, since only a real Playwright
can find it missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.docs_site import URL
from tests.drawing import drawn_site, shell

from dossier.config.load import ConfigError, load_sources
from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors import browser
from dossier.infrastructure.connectors.web import WebConnector, WebKeys


def refusal(tmp_path: Path, render: str) -> str:
    path = tmp_path / "sources.yaml"
    path.write_text(
        f"sources:\n  - id: vendor-docs\n    type: web\n    url: {URL}\n    render: {render}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as error:
        load_sources(path, connectors={"web": WebKeys})
    return str(error.value)


class NoBrowser:
    """A browser that must never be opened."""

    def __call__(self):
        raise AssertionError("a browser was started for a source that draws nothing")


class TestRenderIsBrowserAndAMissingBrowserIsNamed:
    """R1.42 — what `render:` may say, and what is said when the browser is missing."""

    @pytest.mark.parametrize("render", ["chrome", "true"])
    def test_render_that_is_not_browser_is_refused(self, tmp_path: Path, render: str):
        """Example 1: the one where `render:` names another browser, or is a switch."""
        message = refusal(tmp_path, render)

        assert "vendor-docs" in message and "render" in message

    def test_render_browser_without_playwright_is_refused_naming_the_extra(self, monkeypatch):
        """Example 2: the one where `dossier[browser]` was never installed."""
        monkeypatch.setattr(browser, "installed", lambda: False)
        config = SourceConfig(
            id="vendor-docs", type="web", options={"url": URL, "render": "browser"}
        )

        with pytest.raises(ValueError) as raised:
            WebConnector.from_config(config, workspace=Path("."))

        assert "dossier[browser]" in str(raised.value) and "vendor-docs" in str(raised.value)

    def test_render_browser_with_playwright_builds(self, monkeypatch):
        """Row 2's other side: nothing is started when the connector is built."""
        monkeypatch.setattr(browser, "installed", lambda: True)
        config = SourceConfig(
            id="vendor-docs", type="web", options={"url": URL, "render": "browser"}
        )

        assert isinstance(WebConnector.from_config(config, workspace=Path(".")), WebConnector)

    def test_without_render_no_browser_is_started(self):
        """Counter-example, row 4: the one where every page is held as sent (R1.43)."""
        site = drawn_site(escalation=shell("/api/escalation"))
        connector = WebConnector(url=URL, browser=NoBrowser(), transport=site.transport())

        item = connector.fetch("escalation")

        assert item.payload == shell("/api/escalation").encode()
