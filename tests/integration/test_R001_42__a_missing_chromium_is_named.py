"""R1.42 — a Chromium that is not installed is named, never fetched.

Row 3, for real: Playwright installed, and its browsers looked for in an empty
folder. The page fails naming the command that installs Chromium, and the
folder is still empty afterwards: `dossier` never downloads a browser itself.

`live`: it needs `dossier[browser]`, and starts Playwright's driver.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.docs_site import URL
from tests.drawing import drawn_site, shell

from dossier.infrastructure.connectors.browser import INSTALL_CHROMIUM
from dossier.infrastructure.connectors.web import WebConnector, WebRequestFailed

pytestmark = pytest.mark.live
pytest.importorskip("playwright", reason="needs dossier[browser]")


class TestAMissingChromiumIsNamed:
    """R1.42 row 3 — the command is named, and nothing is downloaded."""

    def test_a_page_fails_naming_the_command_that_installs_chromium(
        self, tmp_path: Path, monkeypatch
    ):
        """Example 3: the one where Playwright looks for its browsers in an empty folder."""
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        site = drawn_site(escalation=shell("/api/escalation"))
        connector = WebConnector(url=URL, render="browser", transport=site.transport())

        with pytest.raises(WebRequestFailed) as raised:
            connector.fetch("escalation")

        assert INSTALL_CHROMIUM in str(raised.value)
        assert list(tmp_path.iterdir()) == []
