"""R8.22 — an image in an HTML file is written as its alt text and the name of its
file, and never as its URL or its data.

The alt text is what a reader who cannot see the image is told, so it is the
image's words. The file name ties it to the file, which is often its own
document beside the page. The URL is neither: a host and a query string a model
could quote. An export often inlines its images as `data:` URIs, and written as
markdownify writes them they would put megabytes of base64 into the note.

`PLAY-4003` is `tests/fixtures/documents/exports/PLAY-4003-latency-dashboard-export.html`,
a Grafana panel shared as a page whose whole body is one image.
"""

from __future__ import annotations

from pathlib import Path

from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

PANEL = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "exports"
    / "PLAY-4003-latency-dashboard-export.html"
)
PIXELS = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4"


def converted(html: str) -> str:
    return HtmlMarkdownConverter().convert(html.encode("utf-8"), {}).decode("utf-8")


class TestAnImageIsItsAltTextAndItsFile:
    """R8.22 — words a reader is told, and the file they belong to."""

    def test_the_alt_text_and_the_file_name(self):
        """Example 1: the one where the image says what it shows."""
        written = converted('<img src="panel-checkout-p99.png" alt="Checkout p99 latency">')

        assert written == "![Checkout p99 latency](panel-checkout-p99.png)\n"

    def test_an_image_with_no_alt_text_is_its_file_name(self):
        """Example 2: the one where a whole page is one unlabelled image."""
        written = HtmlMarkdownConverter().convert(PANEL.read_bytes(), {}).decode("utf-8")

        assert written == "![panel-checkout-p99.png](panel-checkout-p99.png)\n"

    def test_the_host_and_the_query_are_not_kept(self):
        """Example 3: the one where the image is served by a dashboard."""
        written = converted('<img src="https://grafana.example/render/d/p99.png?from=now-6h">')

        assert written == "![p99.png](p99.png)\n"
        assert "grafana.example" not in written and "now-6h" not in written

    def test_inline_data_is_not_written(self):
        """Counter-example, row 4: the one where the image is its own base64."""
        written = converted(
            f'<img src="data:image/png;base64,{PIXELS}" alt="Checkout p99 latency">'
        )

        assert written == "![Checkout p99 latency]()\n"
        assert "base64" not in written and PIXELS not in written

    def test_inline_data_with_no_alt_text_writes_nothing(self):
        """Counter-example, row 5: the one where there is nothing to say about it."""
        written = converted(
            f'<p>Before.</p><img src="data:image/png;base64,{PIXELS}"><p>After.</p>'
        )

        assert "!" not in written and "base64" not in written
        assert "Before." in written and "After." in written
