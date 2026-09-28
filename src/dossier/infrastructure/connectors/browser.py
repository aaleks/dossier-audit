"""A headless browser that draws a page from bytes already fetched (spec 001, R1.40 - R1.42).

Some sites send a page as a script that writes it. The web connector asks for
the page itself, as it asks for every page, and hands what the site answered to
a browser here. The browser runs the page's scripts, and asks the connector
about every request they make (`decide`): the connector answers the page's own
document and its site's requests itself, lets the browser send a request to
another host, and refuses the rest (R1.41).

[Playwright](https://playwright.dev/python/) drives Chromium. It is the extra
`dossier[browser]`, and it is imported only when a browser is opened: a source
that does not say `render: browser` never imports it. The Chromium it drives is
installed by `playwright install chromium-headless-shell`, and a missing one is
named, never downloaded (R1.42).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

# What installs each half, named in the errors that ask for them (R1.42).
EXTRA = "dossier[browser]"
INSTALL_CHROMIUM = "playwright install chromium-headless-shell"

# How a navigation that leaves the page is refused without losing the page. A
# navigation aborted outright replaces the drawn page with Chromium's error
# page; one answered `204 No Content` is dropped, and the page stays (R1.41 row 6).
NO_CONTENT = 204


class DrawFailed(RuntimeError):
    """A page could not be drawn, or no browser could be started to draw it."""


@dataclass(frozen=True)
class Asked:
    """One request a page being drawn makes, as the browser describes it."""

    url: str
    method: str
    # Playwright's resource type: `document`, `script`, `stylesheet`, `fetch`,
    # `xhr`, `image`, `font`, `media`, ...
    kind: str
    navigation: bool
    main_frame: bool


@dataclass(frozen=True)
class Answer:
    """What a request is answered with, by the connector rather than the network."""

    status: int
    headers: Mapping[str, str]
    body: bytes


# Answer it with these bytes; let the browser send it; refuse it; or, for a
# navigation away from the page, keep the page where it is.
Decision = Answer | Literal["send", "refuse", "stay"]


class Browser(Protocol):
    """Draws pages, one at a time, for as long as it is open."""

    def draw(self, url: str, decide: Callable[[Asked], Decision]) -> str:
        """The page at `url` as drawn: its DOM, written out as HTML."""
        ...


def installed() -> bool:
    """Whether Playwright is installed, found without importing it (R1.42 row 2)."""
    return importlib.util.find_spec("playwright") is not None


class Chromium:
    """Playwright's headless Chromium, opened for one crawl or one page, and closed after it.

    `outside` answers what the browser would send to another host. A test
    passes it, so that a page drawn in the suite reaches no network; `dossier`
    never does, and the browser sends those requests itself.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float,
        outside: Callable[[Asked], Answer] | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout_seconds
        self._outside = outside
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def __enter__(self) -> Chromium:
        from playwright.sync_api import Error, sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch()
        except Error as error:
            self._playwright.stop()
            if "Executable doesn't exist" in str(error):
                raise DrawFailed(
                    "Playwright's Chromium is not installed, so no page can be drawn. "
                    f"Install it with `{INSTALL_CHROMIUM}`; dossier never downloads "
                    "a browser itself (R1.42)"
                ) from None
            raise DrawFailed(f"Chromium could not be started: {_first_line(error)}") from None
        # A service worker answers a page's requests where no route sees them,
        # and a download is a file, not the page.
        self._context = self._browser.new_context(
            user_agent=self._user_agent, service_workers="block", accept_downloads=False
        )
        return self

    def __exit__(self, *exc_info: object) -> None:
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._playwright.stop()

    def draw(self, url: str, decide: Callable[[Asked], Decision]) -> str:
        """The page at `url` once it has loaded and its requests have gone quiet (R1.40).

        Every request it makes, its own document included, is `decide`'s to
        answer. A page that is not quiet within the timeout fails: half a page
        is not held.
        """
        from playwright.sync_api import Error
        from playwright.sync_api import TimeoutError as Timeout

        page = self._context.new_page()

        def route(route: Any) -> None:
            request = route.request
            asked = Asked(
                url=request.url,
                method=request.method,
                kind=request.resource_type,
                navigation=request.is_navigation_request(),
                main_frame=request.frame == page.main_frame,
            )
            decision = decide(asked)
            if isinstance(decision, Answer):
                route.fulfill(
                    status=decision.status, headers=dict(decision.headers), body=decision.body
                )
            elif decision == "send" and self._outside is not None:
                answer = self._outside(asked)
                route.fulfill(
                    status=answer.status, headers=dict(answer.headers), body=answer.body
                )
            elif decision == "send":
                route.continue_()
            elif decision == "stay":
                route.fulfill(status=NO_CONTENT)
            else:
                route.abort()

        try:
            page.route("**/*", route)
            page.goto(url, wait_until="networkidle", timeout=self._timeout * 1000)
            return page.content()
        except Timeout:
            raise DrawFailed(
                f"{url} did not finish drawing: its requests had not gone quiet after "
                f"{self._timeout:g} seconds, and half a page is not held (R1.40)"
            ) from None
        except Error as error:
            raise DrawFailed(f"{url} could not be drawn: {_first_line(error)}") from None
        finally:
            page.close()


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
