"""R8.32 — `html-markdown` reads a page in the charset the page declares, and in
UTF-8 when it declares none.

A byte-order mark decides first. Then `<meta charset>`, or `<meta http-equiv=
"Content-Type" content="…; charset=…">`, in the page's first 1024 bytes, found by
BeautifulSoup's `EncodingDetector.find_declared_encoding`, which finds an XML
declaration's `encoding` too. A declaration is the document saying what it is,
not a guess, so R8.1 holds. A page that declares nothing is read as UTF-8, and
fails as R8.21 row 4 fails.

Two names are read as a browser reads them, by the WHATWG Encoding Standard:
every label it gives windows-1252 as windows-1252, and one naming UTF-16, with
no byte-order mark, as UTF-8.
"""

from __future__ import annotations

import pytest

from dossier.infrastructure.converters.html_markdown import HtmlMarkdownConverter

# Copied from spec 008, which copied them from the Standard's table
# (https://encoding.spec.whatwg.org/#names-and-labels), not from the converter.
WINDOWS_1252_LABELS = [
    "ansi_x3.4-1968",
    "ascii",
    "cp1252",
    "cp819",
    "csisolatin1",
    "ibm819",
    "iso-8859-1",
    "iso-ir-100",
    "iso8859-1",
    "iso88591",
    "iso_8859-1",
    "iso_8859-1:1987",
    "l1",
    "latin1",
    "us-ascii",
    "windows-1252",
    "x-cp1252",
]
# The Standard's labels for UTF-16LE and UTF-16BE.
UTF_16_LABELS = [
    "csunicode",
    "iso-10646-ucs-2",
    "ucs-2",
    "unicode",
    "unicodefeff",
    "unicodefffe",
    "utf-16",
    "utf-16be",
    "utf-16le",
]


def converted(payload: bytes) -> str:
    return HtmlMarkdownConverter().convert(payload, {}).decode("utf-8")


def failure(payload: bytes) -> str:
    with pytest.raises(ValueError) as error:
        converted(payload)
    return str(error.value)


class TestAnHtmlFileIsReadInTheCharsetItDeclares:
    """R8.32 — what the page says it is, and UTF-8 when it says nothing."""

    def test_a_page_declaring_windows_1252_is_read_in_it(self):
        """Row 1: the one where an older wiki saved `é` as the byte `0xE9`."""
        payload = (
            b'<html><head><meta charset="windows-1252"></head>'
            b"<body><p>Caf\xe9 reopened at 09:54</p></body></html>"
        )

        assert "Café reopened at 09:54" in converted(payload)

    def test_a_charset_named_by_http_equiv_is_the_one_read(self):
        """Row 2: the one where the declaration is the older `http-equiv` form."""
        payload = (
            '<html><head><meta http-equiv="Content-Type" '
            'content="text/html; charset=iso-8859-1"></head>'
            "<body><p>Résolu à Zürich</p></body></html>"
        ).encode("iso-8859-1")

        assert "Résolu à Zürich" in converted(payload)

    def test_windows_1252_that_declares_nothing_fails_naming_utf8(self):
        """Counter-example (row 3): the one where the encoding would have to be guessed."""
        message = failure("<p>Résolu le 2026-04-18</p>".encode("cp1252"))

        assert "html-markdown" in message and "UTF-8" in message

    def test_a_charset_nobody_knows_fails_naming_it(self):
        """Counter-example (row 4): the one where the page names a charset nothing reads."""
        message = failure(
            b'<html><head><meta charset="x-made-up"></head><body><p>Resolved.</p></body></html>'
        )

        assert "html-markdown" in message and "x-made-up" in message

    def test_a_page_declaring_utf8_that_is_not_fails_naming_utf8(self):
        """Counter-example (row 5): the one where the declaration and the bytes disagree."""
        message = failure(
            b'<html><head><meta charset="utf-8"></head><body><p>Caf\xe9</p></body></html>'
        )

        assert "html-markdown" in message and "UTF-8" in message

    def test_a_byte_order_mark_outranks_the_declaration(self):
        """The rule's first sentence: the one where a page re-saved as UTF-8, with a BOM,
        still has the `<meta>` that says windows-1252."""
        payload = (
            b'\xef\xbb\xbf<html><head><meta charset="windows-1252"></head>'
            b"<body><p>Caf\xc3\xa9</p></body></html>"
        )

        written = converted(payload)

        assert "Café" in written and "Ã" not in written

    def test_a_declaration_after_the_first_1024_bytes_is_not_read(self):
        """The rule's second sentence: the one where the `<meta>` comes too late to count."""
        payload = (
            b"<html><head><!-- " + b"x" * 1024 + b' --><meta charset="windows-1252"></head>'
            b"<body><p>Caf\xe9</p></body></html>"
        )

        message = failure(payload)

        assert "html-markdown" in message and "UTF-8" in message

    def test_iso_8859_1_is_read_as_a_browser_reads_it(self):
        """Row 6: the one where `0x96` is an en dash to a browser and a control
        character to Latin-1."""
        payload = (
            b'<html><head><meta charset="iso-8859-1"></head>'
            b"<body><h1>PLAY-4005 \x96 Connection pool exhausted</h1></body></html>"
        )

        written = converted(payload)

        assert "PLAY-4005 – Connection pool exhausted" in written
        assert "\x96" not in written

    @pytest.mark.parametrize("label", WINDOWS_1252_LABELS)
    def test_every_label_the_standard_gives_windows_1252_is_read_as_it(self, label):
        """Row 6, for each of the Standard's labels: the one where Python knows some
        of them as something else, and some of them not at all."""
        payload = f'<meta charset="{label}"><p>Caf\xe9 \x96 09:54</p>'.encode("latin-1")

        assert "Café – 09:54" in converted(payload)

    @pytest.mark.parametrize("label", UTF_16_LABELS)
    def test_a_page_naming_utf16_without_a_byte_order_mark_is_read_as_utf8(self, label):
        """Counter-example (row 7): the one where the declaration was found in the
        bytes as ASCII, so they are not two to a character."""
        payload = f'<meta charset="{label}"><p>Café</p>'.encode()

        assert "Café" in converted(payload)

    def test_a_utf16_page_with_its_byte_order_mark_is_read_as_utf16(self):
        """Row 7's limit: the one where the mark decides first, and the page is UTF-16."""
        payload = b"\xff\xfe" + '<meta charset="utf-16"><p>Café</p>'.encode("utf-16-le")

        assert "Café" in converted(payload)

    def test_an_xml_declaration_is_a_declaration(self):
        """Row 8: the one where an XHTML export says what it is before its `<html>`."""
        payload = (
            b'<?xml version="1.0" encoding="windows-1252"?>\n'
            b"<html><body><p>Caf\xe9 reopened at 09:54</p></body></html>"
        )

        assert "Café reopened at 09:54" in converted(payload)
