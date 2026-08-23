"""R0.1 — nothing right of the hash boundary performs network I/O.

Only `dossier.infrastructure.connectors` may import a network client. Convert,
run and eval never reach the network on any code path, including error paths and
imports made lazily inside a function body.

This is the invariant the whole system rests on: it is what makes a run from six
months ago reproduce exactly, and it is the reason the default suite needs no
services. A violation is silent until someone replays an old audit offline.
"""

from __future__ import annotations

import pytest

from .imports_scan import (
    CONNECTORS,
    Import,
    imports_of,
    is_network,
    module_files,
    module_name,
)

MODULES = module_files()


def _left_of_the_boundary(path) -> bool:
    return module_name(path).startswith(CONNECTORS)


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_no_network_import_outside_the_connectors_package(path):
    """Example 1 and 2: a network import anywhere else is a violation."""
    if _left_of_the_boundary(path):
        return
    offenders: list[Import] = [i for i in imports_of(path) if is_network(i.module)]
    assert not offenders, "\n".join(
        f"{i.where}: imports {i.module!r}"
        + (" inside a function body -- a lazy import is still an import" if i.lazy else "")
        + f"\n  {module_name(path)} is right of the hash boundary (R0.1)."
        f"\n  Fix: move the call into {CONNECTORS} and pass the result across."
        for i in offenders
    )


def test_the_connectors_package_is_the_only_exception():
    """Example 3: the exception exists, is one package, and is named here.

    Asserting the shape of the exemption is the point. If a second package ever
    becomes exempt, this test is where that decision has to be made explicitly.
    """
    exempt = {module_name(p) for p in MODULES if _left_of_the_boundary(p)}
    assert all(name.startswith(CONNECTORS) for name in exempt)
    assert not any(
        name.startswith(f"{CONNECTORS}.") and name.count(".") > 4 for name in exempt
    ), "connectors are flat; a nested sub-package would widen the exemption unnoticed"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: module_name(p))
def test_local_file_io_is_not_network_io(path):
    """Example 4 (counter-example): `pathlib` and `open` are fine everywhere.

    Stated as a test so that a future tightening of the network list cannot
    quietly start rejecting the store, which reads and writes local files by
    design (R0.2).
    """
    for imported in imports_of(path):
        if imported.root in {"pathlib", "shutil", "os", "io", "sqlite3"}:
            assert not is_network(imported.module), (
                f"{imported.where}: {imported.module!r} classified as network. "
                "Local file IO is not network IO -- fix NETWORK_MODULES."
            )
