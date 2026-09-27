"""The layer boundaries in `docs/architecture.md`, enforced.

Not a spec: nothing here is a product claim. These are the structural rules that
keep the product rules provable -- chiefly that `domain/` stays pure enough to be
tested with a plain dict and mutated in minutes.

Contracts catch imports. They do not catch a decision sitting in the wrong layer;
that is the `architecture-guardian` agent's job, and no linter will find it.
"""

from __future__ import annotations

import pytest

from .imports_scan import (
    LAYERS,
    PACKAGE,
    attribute_uses,
    imports_of,
    is_stdlib,
    layer_of,
    module_files,
    module_name,
)

# Which dossier layers each layer may import. Dependencies point one way, and
# `cli` is the only composer -- it is the only place that knows which concrete
# connector, store and model client are in play.
ALLOWED_LAYER_IMPORTS: dict[str, set[str]] = {
    "domain": set(),
    "application": {"domain"},
    "infrastructure": {"domain"},
    "config": {"domain"},
    "cli": {"domain", "application", "infrastructure", "config"},
}

# The purity boundary. Everything else domain needs, it takes as an argument.
DOMAIN_THIRD_PARTY = {"pydantic"}

# Stdlib modules that would break purity even though they are stdlib.
DOMAIN_FORBIDDEN_STDLIB = {
    "os",
    "io",
    "pathlib",
    "shutil",
    "sqlite3",
    "subprocess",
    "random",
    "secrets",
    "tempfile",
    "logging",
    "urllib",
}

# Submodules of a forbidden package that are pure, and so allowed after all.
# `urllib.parse` is string handling: it opens nothing and reads nothing, which is
# why the network scan already lets it through anywhere (imports_scan.py). The
# rest of `urllib` stays out; `urllib.request` reaches the network.
DOMAIN_PURE_SUBMODULES = ("urllib.parse",)

# Reading any of these makes an output depend on something that is not an input.
NONDETERMINISTIC_USES = (
    "datetime.now",
    "datetime.today",
    "datetime.utcnow",
    "time.time",
    "time.monotonic",
    "uuid.uuid1",
    "uuid.uuid4",
    "os.environ",
    "os.getenv",
    "random.random",
    "random.choice",
    "random.shuffle",
)

MODULES = module_files()
DOMAIN_MODULES = module_files("domain")


def test_every_declared_layer_package_exists():
    """An uncovered package is an unenforced boundary."""
    missing = [layer for layer in LAYERS if not (PACKAGE / layer / "__init__.py").exists()]
    assert not missing, f"declared in docs/architecture.md but absent: {missing}"


def test_no_package_escapes_a_contract():
    """A new top-level package under dossier/ must be given a contract."""
    uncovered = sorted(
        entry.name
        for entry in PACKAGE.iterdir()
        if entry.is_dir() and not entry.name.startswith("_") and entry.name not in LAYERS
    )
    assert not uncovered, (
        f"{uncovered} sits under src/dossier/ with no layer contract. "
        "Add it to LAYERS and to docs/architecture.md, or move it into a layer."
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_layer_dependencies_point_one_way(path):
    layer = layer_of(path)
    if layer is None:
        return
    allowed = ALLOWED_LAYER_IMPORTS[layer]
    offenders = []
    for imported in imports_of(path):
        parts = imported.module.split(".")
        if parts[0] != "dossier" or len(parts) < 2:
            continue
        target = parts[1]
        if target in LAYERS and target != layer and target not in allowed:
            offenders.append(f"{imported.where}: {layer} imports {imported.module}")
    assert not offenders, "\n".join(
        offenders + [f"  {layer} may import: {sorted(allowed) or 'nothing'}"]
    )


@pytest.mark.parametrize("path", DOMAIN_MODULES, ids=lambda p: module_name(p))
def test_domain_imports_only_stdlib_and_pydantic(path):
    """The purity boundary. This is what makes domain tests need no fixtures."""
    offenders = []
    for imported in imports_of(path):
        root = imported.root
        if root == "dossier" or root in DOMAIN_THIRD_PARTY:
            continue
        if any(
            imported.module == pure or imported.module.startswith(f"{pure}.")
            for pure in DOMAIN_PURE_SUBMODULES
        ):
            continue
        if root in DOMAIN_FORBIDDEN_STDLIB:
            offenders.append(
                f"{imported.where}: domain imports {imported.module!r} -- "
                "the environment arrives as an argument, not by reaching for it"
            )
        elif not is_stdlib(imported.module):
            offenders.append(
                f"{imported.where}: domain imports third-party {imported.module!r}. "
                f"Only {sorted(DOMAIN_THIRD_PARTY)} is permitted here."
            )
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize("path", DOMAIN_MODULES, ids=lambda p: module_name(p))
def test_domain_is_deterministic(path):
    """Same input, same output. Take a clock or an id generator as a parameter.

    R0.4 and R5.6 are claims about byte-identical results across machines. A
    single `datetime.now()` in this layer makes them untestable.
    """
    offenders = [
        f"{use.where}: {use.dotted}"
        for use in attribute_uses(path)
        if use.dotted in NONDETERMINISTIC_USES
    ]
    assert not offenders, "\n".join(
        offenders + ["  Pass the value in instead -- see docs/architecture.md."]
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_only_cli_exits_the_interpreter(path):
    """A library that kills the process cannot be used from a test or a notebook."""
    if layer_of(path) == "cli":
        return
    offenders = [
        f"{use.where}: {use.dotted}"
        for use in attribute_uses(path)
        if use.dotted in ("sys.exit", "os._exit")
    ]
    assert not offenders, "\n".join(
        offenders + ["  Raise ValueError for anything a caller could fix; cli/ picks the code."]
    )


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_only_config_reads_the_environment(path):
    """R1.8: credentials come from the environment, and only one layer reads it."""
    if layer_of(path) == "config":
        return
    offenders = [
        f"{use.where}: {use.dotted}"
        for use in attribute_uses(path)
        if use.dotted in ("os.environ", "os.getenv")
    ]
    assert not offenders, "\n".join(
        offenders + ["  dossier.config reads the environment and passes values in."]
    )
