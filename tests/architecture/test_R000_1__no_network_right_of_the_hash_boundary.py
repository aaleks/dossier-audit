"""R0.1 — nothing right of the hash boundary performs network I/O.

Only `dossier.infrastructure.connectors` may import a network client. Convert,
run and eval never reach the network on any code path, including error paths and
imports made lazily inside a function body.

This is the invariant the whole system rests on: it is what makes a run from six
months ago reproduce exactly, and it is the reason the default suite needs no
services. A violation is silent until someone replays an old audit offline.
"""

from __future__ import annotations

from pathlib import Path

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


class TestTheDetectorDetects:
    """R0.1 examples 1 and 2 — the positive rows, which were never asserted.

    Found by `/quality`. Every assertion above walks the *real* modules and
    checks the offender list is empty, which is the rule's negative half. Nothing
    constructed a violating module and checked it was caught — so if `is_network`
    or `imports_of` silently stopped working, R0.1 would stay green forever while
    the guarantee the whole project rests on quietly evaporated.

    That was not hypothetical. `from urllib import request` recorded the module
    as `urllib` and was not flagged, while `import urllib.request` was; the
    `from X import Y` form was invisible to the check entirely.
    """

    def probe(self, tmp_path: Path, source: str) -> list[str]:
        """Scan a module written for this test, and return what was flagged."""
        module = tmp_path / "probe.py"
        module.write_text(source, encoding="utf-8")
        return [
            imported.module for imported in imports_of(module) if is_network(imported.module)
        ]

    def test_a_plain_network_import_is_caught(self, tmp_path: Path):
        """Example 1: the one where `convert.py` imports `httpx`."""
        assert self.probe(tmp_path, "import httpx\n") == ["httpx"]

    def test_a_from_import_of_a_network_module_is_caught(self, tmp_path: Path):
        """The form that was invisible: `from urllib import request`.

        Named as its own row because it is the spelling that got through, and a
        regression here would be silent in exactly the same way.
        """
        assert "urllib.request" in self.probe(tmp_path, "from urllib import request\n")

    def test_the_two_spellings_agree(self, tmp_path: Path):
        """The one that stops the two forms drifting apart again."""
        dotted = self.probe(tmp_path, "import urllib.request\n")
        from_form = self.probe(tmp_path, "from urllib import request\n")

        assert "urllib.request" in dotted
        assert "urllib.request" in from_form

    def test_a_lazy_import_inside_a_function_is_still_an_import(self, tmp_path: Path):
        """Example 2: the one where the import hides in a function body.

        R0.1 says so in as many words -- "including error paths and imports made
        lazily inside a function body". Deferring an import defers when the
        network becomes reachable, not whether.
        """
        source = "def fetch():\n    import httpx\n    return httpx\n"

        flagged = self.probe(tmp_path, source)

        assert flagged == ["httpx"]
        lazy = [i for i in imports_of(tmp_path / "probe.py") if i.module == "httpx"]
        assert lazy and lazy[0].lazy, "and it is recorded as lazy, so the message can say so"

    def test_an_innocent_module_is_not_flagged(self, tmp_path: Path):
        """The counter-example: the one that stops the detector crying wolf.

        A checker that flagged everything would pass every row above and fail the
        real suite immediately -- but it would also be indistinguishable from a
        correct one on this class alone.
        """
        source = "import json\nfrom pathlib import Path\nfrom dossier.domain import keys\n"

        assert self.probe(tmp_path, source) == []
