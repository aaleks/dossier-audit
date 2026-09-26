"""`text/csv` read as the `markdown` kind: the register as a markdown table.

`dossier` ships `text-csv`, which writes a CSV's text as it stands (R8.23), and
spec 008 argues against exactly this converter: a table rewrites every row, so
a model quoting what it was shown quotes text the file does not hold. Task 4 of
the exercise is testing that argument rather than taking it on trust, which is
why this is here, and why the solution's workspace installs it and does not name
it.

The same package, the same kind, a different media type: a pair is two halves,
and only one of them moved from `play-html-markdown`.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping


class CsvTableConverter:
    """A CSV's rows as a markdown table, header first."""

    id = "play-csv-table"
    version = "0.1.0"
    media_type = "text/csv"
    kind = "markdown"
    # Opt-in from the start: it claims the pair `text-csv` answers, and an
    # opt-in converter answers only in a workspace that names it (R8.13).
    opt_in = True

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

    Escaped because an unescaped `|` would split the cell in two. A backslash is
    still a character the file does not hold, and a model quoting the cell as it
    reads, without it, quotes a span the artifact does not contain (task 4).
    """
    return "| " + " | ".join(str(cell).replace("|", "\\|").strip() for cell in cells) + " |"
