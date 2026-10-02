"""Whether `dossier` is installed with the entry points its source declares (R0.18).

Connectors, converters, model and embedding providers, chunkers and MLflow's
credential provider are all found by entry point, and entry points come from
the metadata written when `dossier` was installed. An install older than an
entry point cannot find it, and fails on whatever needed it, naming a type or a
provider as missing while the source plainly holds it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# Group, then name, then the target it loads: `dossier.models`, `ollama`,
# `dossier.infrastructure.models.ollama:ollama`.
EntryPoints = Mapping[str, Mapping[str, str]]


def stale_entry_points(*, declared: EntryPoints, installed: EntryPoints) -> list[str]:
    """Each way the installed entry points differ from the declared ones, in order.

    Missing, left over, or pointing elsewhere: any of the three is an install
    made from another version of the source.
    """
    found: list[str] = []
    for group in sorted(set(declared) | set(installed)):
        wanted, held = declared.get(group, {}), installed.get(group, {})
        for name in sorted(set(wanted) | set(held)):
            if name not in held:
                found.append(f"{group} {name} is declared and not installed")
            elif name not in wanted:
                found.append(f"{group} {name} is installed and no longer declared")
            elif wanted[name] != held[name]:
                found.append(
                    f"{group} {name} is declared as {wanted[name]}, installed as {held[name]}"
                )
    return found


def stale_install_line(differences: Sequence[str]) -> str:
    """The one line saying the install is stale, and the one fix (R0.18)."""
    return (
        "dossier is installed from older metadata than its source: "
        f"{'; '.join(differences)}. Reinstall it: uv sync"
    )
