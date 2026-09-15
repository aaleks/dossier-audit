"""The environment `dossier.config` reads through, with `.env` beneath it (R9.11).

Endpoints and keys are per machine (R9.2, R9.8), and a `.env` file in the
working directory saves exporting them by hand. It fills only what the shell
leaves unset -- what a person set for this one command is the most specific
thing they said -- and only `DOSSIER_` variables are read from it, so the file
cannot steer anything else.

It is read into a mapping and never written to the process environment. A
subprocess, a library, or the next test in the same interpreter sees exactly
the environment it was started with.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DOTENV = ".env"
_PREFIX = "DOSSIER_"


def environment(directory: Path, *, shell: Mapping[str, str] | None = None) -> dict[str, str]:
    """The shell's environment, with `directory/.env` filling what it leaves unset.

    A variable the shell sets wins even when it is set to nothing: set and
    empty is still something the person said. No `.env` is not an error --
    each provider's default applies (R9.11 row 3).
    """
    shell = os.environ if shell is None else shell
    return {**_dotenv(directory / DOTENV), **shell}


def _dotenv(path: Path) -> dict[str, str]:
    """`KEY=value` lines from a `.env` file, `DOSSIER_` keys only.

    Blank lines and `#` comments are skipped, and one pair of matching quotes
    around a value is removed: a quoted URL kept its quotes would be an endpoint
    nobody can reach, reported as unreachable rather than as mistyped.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key.startswith(_PREFIX):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values
