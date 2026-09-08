"""R8.7 — adding a converter requires no edit to the `dossier` core package.

A new converter is a package declaring a `dossier.converters` entry point. If
adding one means touching a file under `src/dossier/`, the interface has failed.

This matters more for converters than it does for connectors. A PDF converter is
a large dependency with its own release cadence; pinning every pipeline in
existence to it, because it happens to live in the core package, is exactly the
coupling this rule prevents.

Example 2 -- a third party registering an `.xls` converter -- would need a real
package installed to prove, so it is simulated through the same mechanism a third
party would use.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dossier.infrastructure.converters.registry import (
    ENTRY_POINT_GROUP,
    installed_converters,
)

from .imports_scan import module_files, module_name

# The names a dispatch would have to mention. If one of these appears in a
# comparison anywhere in the core package, something is deciding by type rather
# than by entry point.
CONVERTER_NAMES = {"pdf-markdown", "pdf-images", "markdown-text"}
CONVERTED_MEDIA_TYPES = {"application/pdf", "text/markdown", "text/html"}

# Where these names are legitimate: a converter naming its own claim, and the
# registry naming the group it reads.
CONVERTER_PACKAGE = "dossier.infrastructure.converters"


class TestNoDispatchOnConverterIdentity:
    """R8.7 example 1 — no `match` or `if` on a converter or a media type."""

    @pytest.mark.parametrize("path", module_files(), ids=lambda p: module_name(p))
    def test_no_module_compares_against_a_converter_name(self, path: Path):
        """The one where a `match media_type` in the core would be caught.

        Scoped to comparisons rather than to the string appearing at all: a
        converter names its own media type, and `domain.conversion` legitimately
        holds `DEFAULT_KIND` as a value it never compares a converter against.
        """
        if module_name(path).startswith(CONVERTER_PACKAGE):
            # A converter may name what it claims; it is the thing being named.
            return

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders = []
        forbidden = CONVERTER_NAMES | CONVERTED_MEDIA_TYPES

        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                literals = [
                    operand.value
                    for operand in [node.left, *node.comparators]
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, str)
                ]
                if forbidden.intersection(literals):
                    offenders.append(
                        f"{path.name}:{node.lineno}: compares against a converter name"
                    )
            if isinstance(node, ast.Match):
                for case in node.cases:
                    for sub in ast.walk(case.pattern):
                        if isinstance(sub, ast.Constant) and sub.value in forbidden:
                            offenders.append(
                                f"{path.name}:{sub.lineno}: match on a converter name"
                            )

        assert not offenders, "\n".join(
            offenders + ["  Converters are resolved through the entry point group (R8.7)."]
        )


class TestResolutionGoesThroughEntryPoints:
    """R8.7 — the mechanism itself."""

    def test_the_shipped_converter_is_registered_like_any_other(self):
        """Counter-example (row 3): the one where being in-tree is not special.

        `markdown-text` ships in this package and still registers through the
        same group a third party would use -- no special case, no shortcut, and
        no way for the core to find it other than the one everyone else uses.
        """
        assert "markdown-text" in {converter.id for converter in installed_converters()}

    def test_a_third_party_converter_needs_no_change_to_dossier(self, monkeypatch):
        """Example 2, simulated: the one where an `.xls` converter arrives.

        Registered through the same group, found by the same lookup. What matters
        is that the core package learns of a converter from the group and from
        nowhere else.
        """
        import dossier.infrastructure.converters.registry as registry

        class ExcelConverter:
            id = "xls-markdown"
            version = "0.2.0"
            media_type = "application/vnd.ms-excel"
            kind = "markdown"

            def convert(self, payload: bytes, options) -> bytes:
                return b"| a | b |\n"

        class Point:
            name = "xls-markdown"

            def load(self):
                return ExcelConverter

        monkeypatch.setattr(
            registry,
            "entry_points",
            lambda group: [Point()] if group == ENTRY_POINT_GROUP else [],
        )

        assert [c.id for c in registry.installed_converters()] == ["xls-markdown"]

    def test_the_installed_order_is_stable(self, monkeypatch):
        """The one where the environment's entry-point order must not leak.

        `entry_points()` returns whatever order it likes. Two machines with the
        same packages must see the same list, or anything derived from it varies
        by machine (R5.6).
        """
        import dossier.infrastructure.converters.registry as registry

        def converter(name: str, media_type: str, kind: str):
            return type(
                name, (), {"id": name, "version": "1.0.0",
                           "media_type": media_type, "kind": kind}
            )

        made = [
            converter("z", "text/markdown", "markdown"),
            converter("a", "application/pdf", "markdown"),
        ]
        points = [type("P", (), {"name": c.id, "load": lambda self, c=c: c})() for c in made]

        monkeypatch.setattr(registry, "entry_points", lambda group: points)
        forwards = [c.id for c in registry.installed_converters()]

        monkeypatch.setattr(registry, "entry_points", lambda group: list(reversed(points)))
        backwards = [c.id for c in registry.installed_converters()]

        assert forwards == backwards == ["a", "z"]
