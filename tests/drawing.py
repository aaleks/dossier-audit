"""`vendor-docs` built in the browser, and a browser for the unit suite (R1.40 - R1.43).

The pages of `specs/_fixtures.md` served as shells: a `<div id="app">` naming,
in `data-fetch`, where its text is, and `/assets/app.js`, which asks for it and
writes the answer in. `APP_JS` is that script, and a real headless Chromium runs
it in `tests/integration/test_R001_40…` and `…41…`.

`FakeBrowser` draws the same shells with no Chromium: it asks `decide` for each
request the page would make, in the order Chromium makes them, and writes what
`app.js` would write. A fake of Chromium is a claim about Chromium, and those
integration tests are where the same shells are drawn by the real one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from dossier.infrastructure.connectors.browser import Answer, Asked, Decision
from tests.docs_site import SITE, DocsSite

APP = f"{SITE}/assets/app.js"
API = f"{SITE}/api/escalation"
INDEX_API = f"{SITE}/api/index"
DIAGRAM = f"{SITE}/img/escalation-diagram.png"

TEXT = "Page the incident commander, m.keller, before a Sev 2 is fifteen minutes old."
ESCALATION_TEXT = f"<h1>Escalation</h1><p>{TEXT}</p>"
INDEX_LINKS = (
    '<a href="escalation">Escalation</a>'
    '<a href="runbooks/dns-failover.html">DNS failover</a>'
    '<a href="escalation-matrix.pdf">Escalation matrix</a>'
)

# What `/assets/app.js` does: ask for `data-fetch` and write the answer into the
# `div`, then post to `data-post` and move to `data-go` where a test asks for
# either. `FakeBrowser.draw` is this, without a JavaScript engine.
APP_JS = """
document.addEventListener('DOMContentLoaded', async () => {
  const app = document.getElementById('app');
  if (!app) return;
  if (app.dataset.fetch) {
    const answer = await fetch(app.dataset.fetch);
    if (answer.ok) app.innerHTML = await answer.text();
  }
  if (app.dataset.post) {
    try { await fetch(app.dataset.post, {method: 'POST', body: 'viewed'}); } catch (e) {}
  }
  if (app.dataset.go) window.location.href = app.dataset.go;
});
"""


def shell(
    fetch: str,
    *,
    charset: str = "utf-8",
    extra: str = "",
    app: str = "/assets/app.js",
    attributes: str = "",
) -> str:
    """A page whose text `app.js` writes from `fetch`, as the fixtures' `escalation` is."""
    return (
        f'<!DOCTYPE html><html><head><meta charset="{charset}"><title>Vendor Docs</title>'
        f'</head><body><main><div id="app" data-fetch="{fetch}"{attributes}></div>'
        f'<img src="/img/escalation-diagram.png" alt="Escalation diagram">{extra}</main>'
        f'<script src="{app}"></script></body></html>'
    )


def html(body: str | bytes, charset: str = "utf-8") -> httpx.Response:
    content = body.encode(charset) if isinstance(body, str) else body
    return httpx.Response(
        200, headers={"Content-Type": f"text/html; charset={charset}"}, content=content
    )


def drawn_site(**pages: str) -> DocsSite:
    """`vendor-docs` with `app.js` and its answers, and `pages` (by fixture key) as shells.

    `drawn_site(escalation=shell("/api/escalation"))` serves `escalation` as the
    fixtures' shell.
    """
    site = DocsSite(
        responses={
            APP: httpx.Response(
                200, headers={"Content-Type": "text/javascript"}, content=APP_JS.encode()
            ),
            API: html(ESCALATION_TEXT),
            INDEX_API: html(INDEX_LINKS),
        }
    )
    for key, body in pages.items():
        url = f"{SITE}/ops/" if key == "index" else f"{SITE}/ops/{key}"
        site.responses[url] = html(body)
    return site


class _Loads(HTMLParser):
    """What a page loads, in document order, and its `app` element's attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.loads: list[tuple[str, str]] = []
        self.app: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        named = {name: value or "" for name, value in attrs}
        if tag == "script" and "src" in named:
            self.loads.append(("script", named["src"]))
        elif tag == "img" and "src" in named:
            self.loads.append(("image", named["src"]))
        elif tag == "iframe" and "src" in named:
            self.loads.append(("frame", named["src"]))
        elif named.get("id") == "app":
            self.app = named


@dataclass
class FakeBrowser:
    """A browser that draws `vendor-docs`' shells as `app.js` would, asking `decide` first.

    Pass it where the connector takes a browser: it opens itself. `opened` counts
    how often a browser was started; `sent` is every request the connector left
    to the browser, which a real one would send to another host.
    """

    opened: int = 0
    sent: list[Asked] = field(default_factory=list)
    refused: list[Asked] = field(default_factory=list)

    def __call__(self) -> FakeBrowser:
        return self

    def __enter__(self) -> FakeBrowser:
        self.opened += 1
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def draw(self, url: str, decide) -> str:
        document = self._ask(decide, url, "document", navigation=True)
        assert isinstance(document, Answer), f"the page itself was not answered: {document!r}"
        page = _page(document)
        loads = _Loads()
        loads.feed(page)

        script_ran = False
        for kind, src in loads.loads:
            target = urljoin(url, src)
            if kind == "frame":
                self._ask(decide, target, "document", navigation=True, main_frame=False)
                continue
            answer = self._ask(decide, target, kind)
            # Only a script it was handed runs: one sent to another host is
            # the browser's to fetch, and this browser fetches nothing.
            script_ran = script_ran or (kind == "script" and _ok(answer))

        if script_ran and loads.app:
            if fetched := loads.app.get("data-fetch"):
                answer = self._ask(decide, urljoin(url, fetched), "fetch")
                if _ok(answer):
                    page = _written(page, answer.body.decode("utf-8", errors="replace"))
            if posted := loads.app.get("data-post"):
                self._ask(decide, urljoin(url, posted), "fetch", method="POST")
            if gone := loads.app.get("data-go"):
                self._ask(decide, urljoin(url, gone), "document", navigation=True)
        return page

    def _ask(
        self,
        decide,
        url: str,
        kind: str,
        *,
        method: str = "GET",
        navigation: bool = False,
        main_frame: bool = True,
    ) -> Decision:
        asked = Asked(
            url=url, method=method, kind=kind, navigation=navigation, main_frame=main_frame
        )
        decision = decide(asked)
        if decision == "send":
            self.sent.append(asked)
        elif decision == "refuse":
            self.refused.append(asked)
        return decision


def _ok(decision: Decision) -> bool:
    return isinstance(decision, Answer) and 200 <= decision.status < 300


def _page(answer: Answer) -> str:
    """A page as a browser reads it: in the charset its header names, else UTF-8.

    A script's `fetch(...).text()` is UTF-8 whatever its answer says, as the Fetch
    standard has it, and as Chromium was seen to read one on 2026-09-28.
    """
    content_type = next(
        (value for name, value in answer.headers.items() if name.lower() == "content-type"), ""
    )
    found = re.search(r"charset=([\w-]+)", content_type)
    return answer.body.decode(found.group(1) if found else "utf-8")


def _written(page: str, text: str) -> str:
    """`page` with `text` written into its `app` element, as `app.js` writes it."""
    return re.sub(r'(<div id="app"[^>]*>)</div>', lambda m: f"{m.group(1)}{text}</div>", page)
