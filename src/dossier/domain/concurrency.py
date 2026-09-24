"""How many of a step's documents a run asks a model about at once (R9.19).

Per machine, like where a model is served: the flag, else the environment
`.env` fills, else 1. Never from `pipeline.yaml`, whose hash is the pipeline's
(R13.1). The environment is handed in, so this module reads no `os.environ`.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["CONCURRENCY", "FLAG", "concurrency"]

CONCURRENCY = "DOSSIER_CONCURRENCY"
FLAG = "--concurrency"


def concurrency(environ: Mapping[str, str], *, flag: str | None = None) -> int:
    """How many documents of a step are asked at once: `N`, at least 1 (R9.19).

    The flag wins over the environment, because what is said on the command
    line wins over what the machine is set to. An unset or empty variable is 1,
    the run before this rule. Anything else that is not a whole number of at
    least 1 is refused, naming where it came from. There is no ceiling:
    `dossier` does not know a provider's limit.
    """
    if flag is not None:
        return _count(flag, said=FLAG)
    value = environ.get(CONCURRENCY, "")
    if not value:
        return 1
    return _count(value, said=CONCURRENCY)


def _count(value: str, *, said: str) -> int:
    if value.isascii() and value.isdigit() and int(value) >= 1:
        return int(value)
    raise ValueError(f"{said} is {value!r}; it takes a whole number of at least 1.")
