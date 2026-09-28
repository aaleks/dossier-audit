"""R15.5 — only `dossier review pull` reads a verdict back, and what it reads
reaches the review files and nothing else.

MLflow was something `dossier` wrote to and never an input (R0.10, R12.4,
R13.4, R14.5). Review makes one exception, and this fences it the way each of
those did: structurally, by where the names that read a verdict and the names
of the files it lands in are allowed to appear. A run, a plan, a replay, an
eval or a calibration that cannot name them cannot read them, so a verdict left
on the server cannot move a key, a manifest, an artifact or a score -- which is
rows 3 and 4, stated as the property that makes them true.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from .imports_scan import PACKAGE, imports_of, module_files, module_name

# Every module of the command line: a command in any of them could build a
# review source, so the fence is drawn around all of them.
CLI = sorted((PACKAGE / "cli").glob("*.py"))
# Every name through which a verdict is read, or through which what was read
# is written or applied. Anything naming one of these is on the review path.
REVIEW_NAMES = frozenset(
    {
        "build_review_source",
        "connect_reviews",
        "pull_reviews",
        "apply_candidates",
        "CANDIDATES",
        "FEEDBACK",
    }
)
REVIEW_MODULES = frozenset({"dossier.application.review", "dossier.domain.review"})
# The modules allowed to import them: the review use case itself, the port that
# names what a source returns, the adapter that reads MLflow, and the module
# that holds the two review commands and builds their source.
ALLOWED = frozenset(
    {
        "dossier.application.review",
        "dossier.domain.review",
        "dossier.domain.ports",
        "dossier.infrastructure.tracking.mlflow",
        "dossier.cli.review",
    }
)


def _imports_review_source(path: Path) -> bool:
    """Whether `path` imports the `ReviewSource` port by name, anywhere in it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "dossier.domain.ports"
        and any(alias.name == "ReviewSource" for alias in node.names)
        for node in ast.walk(tree)
    )


def _commands_naming(paths: list[Path], names: frozenset[str]) -> dict[str, set[str]]:
    """Each top-level function in `paths`, and which of `names` its body uses."""
    found: dict[str, set[str]] = {}
    for node in (
        node for path in paths for node in ast.parse(path.read_text(encoding="utf-8")).body
    ):
        if not isinstance(node, ast.FunctionDef):
            continue
        used = {
            inner.id
            for inner in ast.walk(node)
            if isinstance(inner, ast.Name) and inner.id in names
        }
        if used:
            found[node.name] = used
    return found


class TestOnlyReviewPullReadsAVerdict:
    """R15.5 — the one read from MLflow, and the fence around what it reads."""

    def test_only_review_pull_builds_a_review_source(self):
        """Row 1: `build_review_source` called from `review pull` and from nothing else."""
        callers = _commands_naming(CLI, frozenset({"build_review_source"}))

        assert set(callers) == {"review_pull"}

    def test_what_review_writes_is_named_only_by_the_two_review_commands(self):
        """Rows 3 and 4: no other command names the files a pull writes, or reads them."""
        users = set(_commands_naming(CLI, REVIEW_NAMES))

        assert users <= {"review_pull", "review_apply", "build_review_source"}, (
            f"{sorted(users - {'review_pull', 'review_apply', 'build_review_source'})} name "
            "the review path; a verdict would reach them"
        )

    def test_no_module_but_the_review_path_imports_it(self):
        """Rows 3 and 4: run, plan, replay, eval and calibrate cannot reach a verdict."""
        reaching = {
            module_name(path)
            for path in module_files()
            if _imports_review_source(path)
            or any(found.module in REVIEW_MODULES for found in imports_of(path))
        }

        assert reaching <= ALLOWED, f"{sorted(reaching - ALLOWED)} import the review path"

    def test_the_tracker_still_returns_nothing(self):
        """Row 2: the `Tracker` port returns nothing read from the server (R0.10 row 5)."""
        from dossier.domain.ports import Tracker

        returning = {
            name: method.__annotations__.get("return")
            for name, method in inspect.getmembers(Tracker, inspect.isfunction)
            if not name.startswith("_")
            and method.__annotations__.get("return") not in ("None", None)
        }

        assert returning == {}
