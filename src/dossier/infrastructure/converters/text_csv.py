"""A CSV file in, its text out (spec 008, R8.23).

A register saved from a spreadsheet is one of the files a Jira issue or a
Confluence page most often carries, and nothing claimed `(text/csv, markdown)`,
so one such attachment stopped its whole source (R8.5).

Its text is its note. A markdown table was the obvious alternative and was
rejected: it rewrites every row -- `a,b` becomes `| a | b |`, and a `|` in a
cell needs an escape -- so a model quoting the table would quote text the file
does not hold, and the span would not be found (R6.4). Separate from
`text-plain` because a converter claims exactly one pair (R8.3); the two share
their body, not their identity, and their versions move independently (R5.4).
"""

from __future__ import annotations

from collections.abc import Mapping

from dossier.infrastructure.converters._decode import decode_utf8


class TextCsvConverter:
    """`text/csv` to the `markdown` kind."""

    id = "text-csv"
    # Raise this whenever output could change for the same input.
    version = "1.0.0"
    media_type = "text/csv"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The text as written, or a failure naming UTF-8 for any other encoding.

        No encoding is guessed. A guess is a function of whatever detector a
        machine has installed, not of the bytes alone (R8.1).
        """
        return decode_utf8(payload, converter_id=self.id)
