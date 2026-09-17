"""`application/pdf` read as the `markdown` kind: the text a stage will see.

The whole contract is R8.1: the artifact is a pure function of the snapshot bytes
and the declared options. No clock, no locale, no file outside the input, no
network. Everything here reads `payload` and nothing else, which is what makes
`K_convert` -- snapshot hash, converter id, version, options -- a true statement
about the bytes it produced.

`version` is the one promise no test can enforce: raise it whenever output could
change for the same input (R8.2, R5.4). For this converter that includes changing
the pinned `pypdf` range, because the text a page extracts to is that library's
answer, not this module's.
"""

from __future__ import annotations

import io
from collections.abc import Mapping

from pypdf import PdfReader

# What separates one page's text from the next in the artifact. Part of the
# output, so changing it changes every artifact and is a version bump.
PAGE_MARKER = "\n\n<!-- page {number} -->\n\n"


class PdfMarkdownConverter:
    """A PDF's extracted text, one block per page, with a page marker between."""

    id = "pdf-markdown"
    version = "0.1.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The document's text, in page order, as UTF-8.

        A PDF with no text layer converts to an empty artifact rather than
        failing. That is the honest answer -- the bytes really do carry no text --
        and it is exactly what `dossier convert` exists to show before a single
        model call is made (R8.8). A stage that then finds nothing to ground a
        span in reports an ungrounded field (R6.4), which is the right outcome for
        a page nobody can read.

        `options` is accepted and unused: this converter has none. The argument
        stays in the signature because every converter is called the same way, and
        options are part of the key -- so an option nobody reads still produces
        its own cache entry rather than quietly sharing one.
        """
        try:
            reader = PdfReader(io.BytesIO(payload))
        except Exception as error:
            # One document's bytes are bad, which is R8.6's failure and not
            # R8.5's: the configuration is right, this input is not. Raising
            # `ValueError` is how a converter says so -- the run reports this
            # document and audits the rest.
            raise ValueError(f"{self.id} could not read the PDF: {error}") from error

        pages = []
        for number, page in enumerate(reader.pages, start=1):
            pages.append(PAGE_MARKER.format(number=number).strip("\n"))
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages).encode("utf-8")
