"""R1.7 — adding a connector requires no edit to the `dossier` core package.

A new source type is a package declaring an entry point. If adding one means
touching a file under `src/dossier/`, the interface has failed.

Example 2 -- a third-party package registering `sharepoint` -- would need a real
package installed to prove, so it is simulated here by registering a factory
through the same mechanism a third party would use.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dossier.domain.pipeline import SourceConfig
from dossier.infrastructure.connectors.registry import (
    ENTRY_POINT_GROUP,
    UnknownSourceType,
    available_types,
    build_connector,
)

from .imports_scan import module_files, module_name

# The names a dispatch would have to mention. If one appears in a comparison
# anywhere in the core package, something is deciding by type rather than by
# entry point.
CONNECTOR_TYPES = {"folder", "jira", "confluence", "sharepoint"}

# Where the entry point group is legitimately named: the registry that reads it.
REGISTRY = "dossier.infrastructure.connectors.registry"


class TestNoDispatchOnSourceType:
    """R1.7 example 1 — no `match` or `if` on a connector name in the core."""

    @pytest.mark.parametrize("path", module_files(), ids=lambda p: module_name(p))
    def test_no_module_compares_against_a_connector_type_name(self, path: Path):
        """The one where a `match source.type` would be caught.

        Scoped to comparisons rather than to the string appearing at all: a
        connector module naturally mentions its own name in a docstring, and the
        registry names the group it reads.
        """
        if module_name(path).startswith("dossier.infrastructure.connectors"):
            # A connector may mention its own type; it is the thing being named.
            return

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                literals = [
                    operand.value
                    for operand in [node.left, *node.comparators]
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, str)
                ]
                if CONNECTOR_TYPES.intersection(literals):
                    offenders.append(f"{path.name}:{node.lineno}: compares against a type name")
            if isinstance(node, ast.Match):
                for case in node.cases:
                    for sub in ast.walk(case.pattern):
                        if isinstance(sub, ast.Constant) and sub.value in CONNECTOR_TYPES:
                            offenders.append(f"{path.name}:{sub.lineno}: match on a type name")

        assert not offenders, "\n".join(
            offenders + ["  Source types are resolved through the entry point group (R1.7)."]
        )


class TestResolutionGoesThroughEntryPoints:
    """R1.7 — the mechanism itself."""

    def test_the_shipped_folder_connector_is_registered_like_any_other(self):
        """Counter-example (row 3): the one where being in-tree is not special.

        `folder` ships in this package and still registers through the same
        group a third party would use -- no special case, no shortcut.
        """
        assert "folder" in available_types()

    def test_a_source_resolves_to_its_connector(self, tmp_path: Path):
        """The one where configuration becomes a working connector."""
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "INC-4821.md").write_bytes(b"x")

        connector = build_connector(
            SourceConfig(id="incidents-manual", type="folder", options={"path": "inbox"}),
            workspace=tmp_path,
        )

        assert [ref.key for ref in connector.list(None)] == ["INC-4821.md"]

    def test_a_third_party_type_needs_no_change_to_dossier(self, tmp_path: Path, monkeypatch):
        """Example 2, simulated: the one where `sharepoint` arrives from outside.

        Registered through the same group, resolved by the same lookup. Proving
        this with a real installed package would mean building one per test run;
        what matters is that the core package learns the type from the group and
        from nowhere else.
        """
        from importlib.metadata import EntryPoint

        import dossier.infrastructure.connectors.registry as registry

        def fake_sharepoint(config, *, workspace):
            return "a sharepoint connector"

        point = EntryPoint(name="sharepoint", value="x:y", group=ENTRY_POINT_GROUP)
        monkeypatch.setattr(point.__class__, "load", lambda self: fake_sharepoint)
        monkeypatch.setattr(registry, "entry_points", lambda group: [point])

        built = registry.build_connector(
            SourceConfig(id="procedures", type="sharepoint"), workspace=tmp_path
        )

        assert built == "a sharepoint connector"

    def test_an_unknown_type_says_what_is_available(self, tmp_path: Path):
        """The one where the error explains the mechanism.

        Someone hitting this has usually not installed the package. Naming the
        entry point group is what turns the message into an instruction.
        """
        with pytest.raises(UnknownSourceType) as error:
            build_connector(
                SourceConfig(id="procedures", type="sharepoint"), workspace=tmp_path
            )

        message = str(error.value)
        assert "sharepoint" in message
        assert "folder" in message
        assert ENTRY_POINT_GROUP in message

    def test_a_folder_source_without_a_path_is_refused(self, tmp_path: Path):
        """The one where the connector states its own requirement.

        The core package does not know that a folder needs a path; the folder
        connector does, and says so. That is what keeps type-specific knowledge
        out of the core (R1.7).
        """
        with pytest.raises(ValueError) as error:
            build_connector(
                SourceConfig(id="incidents-manual", type="folder"), workspace=tmp_path
            )

        assert "path" in str(error.value)
