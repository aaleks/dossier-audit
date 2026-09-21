"""`text/csv` read as the `markdown` kind: the register as a table a stage reads.

The second pair this package claims, and the reason it is here: a pair is
`(media type, kind)`, and these two converters share a kind and differ in media
type. Nothing about `html-markdown` and nothing about the source's `convert:`
list changes because this one is installed -- which is what "registered against
the pair" buys, and what the version bump in the last task of the exercise makes
visible.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping


class CsvMarkdownConverter:
    """A CSV's rows as a markdown table, header first."""

    id = "csv-markdown"
    version = "0.1.0"
    media_type = "text/csv"
    kind = "markdown"

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """Every row, in file order, as a pipe table.

        The dialect is *not* sniffed. `csv.Sniffer` reads a sample and guesses a
        delimiter, which makes the artifact a function of how much of the file it
        happened to look at -- and a register whose first rows hold no semicolon
        would convert one way today and another way after a row was appended,
        under the same key (R8.1). A comma, declared and fixed, is a worse guess
        and a true one.
        """
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"{self.id} could not decode this CSV as UTF-8: {error}"
            ) from error

        rows = list(csv.reader(io.StringIO(text, newline="")))
        if not rows:
            return b""

        header, *body = rows
        lines = [_row(header), _row("---" for _ in header)]
        lines.extend(_row(row) for row in body)
        return "\n".join(lines).encode("utf-8")


def _row(cells: Iterable[object]) -> str:
    """One table line, with any pipe in a value escaped rather than dropped.

    A dropped character is a value the model is shown that the document does not
    contain, and a span quoted from it would not be found in the source at all.
    """
    return "| " + " | ".join(str(cell).replace("|", "\\|").strip() for cell in cells) + " |"
