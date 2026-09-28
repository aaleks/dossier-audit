"""R8.33 — `html-markdown` writes a page that declares one `<main>` as that
element, without the `<nav>` in it.

`<main>`, or `role="main"`, is where the page's author says its content is.
Every page of a site repeats the site around it -- a header, menus, a sidebar,
a footer -- and those are not in the note of a page that says so. Nothing is
chosen by class name or by how much text a block holds; a page declaring no
`<main>`, or two, is read whole, as R8.21 reads it.

`escalation` is `vendor-docs`' page, as `specs/_fixtures.md` describes it.
"""

from __future__ import annotations

from pathlib import Path

from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

EXPORT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "exports"
    / "PLAY-4001-payment-retries.html"
)

TEXT = "Page the incident commander, m.keller, before a Sev 2 is fifteen minutes old."
ARTICLE = f"<article><h1>Escalation</h1><p>{TEXT}</p></article>"


def escalation(main: str = "<main>{}</main>", article: str = ARTICLE) -> str:
    """`escalation` as `vendor-docs` serves it, its content wrapped as `main` says."""
    content = (
        '<nav><a href="/ops/escalation">Escalation</a>'
        '<a href="/ops/runbooks/dns-failover.html">DNS failover</a></nav>' + article
    )
    return (
        "<!DOCTYPE html><html><head><title>Escalation - Vendor Docs</title></head><body>"
        '<header><a href="/">Vendor Docs</a><form><label>Search</label><input></form></header>'
        '<nav><a href="/ops/">Ops</a><a href="/blog/">Blog</a></nav>'
        + main.format(content)
        + "<footer><p>© 2026 Vendor</p></footer>"
        "</body></html>"
    )


def converted(html: str | bytes) -> str:
    payload = html.encode("utf-8") if isinstance(html, str) else html
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


def chrome_in(note: str) -> list[str]:
    """The parts of the site around the article that are in `note`."""
    return [
        seen
        for seen in ("Vendor Docs", "Search", "Ops", "Blog", "DNS failover", "© 2026 Vendor")
        if seen in note
    ]


class TestAPageThatDeclaresItsMainIsWrittenAsIt:
    """R8.33 — the page's `<main>`, without its `<nav>`, when it declares one."""

    def test_the_note_is_the_article_and_none_of_the_site_around_it(self):
        """Example 1: the one where every page of a site repeats the site."""
        note = converted(escalation())

        assert note == f"# Escalation\n\n{TEXT}\n"

    def test_role_main_declares_it_as_main_does(self):
        """Example 2: the one where the declaration is ARIA's."""
        note = converted(escalation(main='<div role="main">{}</div>'))

        assert note == converted(escalation())

    def test_a_header_inside_main_is_the_articles_own(self):
        """Example 3: the one where only `<nav>` is taken from inside `<main>`."""
        article = f"<article><header><h1>Escalation</h1></header><p>{TEXT}</p></article>"
        note = converted(escalation(article=article))

        assert note.startswith("# Escalation\n")
        assert chrome_in(note) == []

    def test_a_page_declaring_no_main_is_read_whole(self):
        """Counter-example, row 4: the one where an exported file keeps its breadcrumb."""
        note = converted(EXPORT.read_bytes())

        assert "Spaces / Site Reliability / Postmortems / 2026 / PLAY-4001" in note
        assert "# PLAY-4001 — Duplicate payment retries after a queue redelivery\n" in note

    def test_a_page_declaring_two_mains_is_read_whole(self):
        """Counter-example, row 5: the one where choosing one would be a guess."""
        note = converted(escalation(main="<main>{}</main><main><p>Related pages</p></main>"))

        assert chrome_in(note) == [
            "Vendor Docs",
            "Search",
            "Ops",
            "Blog",
            "DNS failover",
            "© 2026 Vendor",
        ]
        assert "Related pages" in note

    def test_a_main_nobody_sees_declares_nothing(self):
        """Counter-example, row 6: the one where the `<main>` is in a template."""
        page = escalation(main="<div>{}</div>").replace(
            "</body>", "<template><main><p>Never rendered.</p></main></template></body>"
        )
        note = converted(page)

        assert "Never rendered." not in note
        assert "Vendor Docs" in note and "© 2026 Vendor" in note
