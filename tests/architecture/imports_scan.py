"""Walk `src/dossier` with `ast` and report what each module imports and calls.

An `ast` walk rather than import-linter, for three reasons recorded in
`docs/architecture.md`: one fewer dependency, no shell-out on Windows, and it
sees an import made lazily inside a function body -- which is exactly how a
network client sneaks past a module-scope contract.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
PACKAGE = SRC / "dossier"

LAYERS = ("domain", "application", "infrastructure", "config", "cli")

# The one package left of the hash boundary (R0.1).
CONNECTORS = "dossier.infrastructure.connectors"

NETWORK_MODULES = frozenset(
    {
        "aiohttp",
        "atlassian",
        "boto3",
        "ftplib",
        "http",
        "httpcore",
        "httplib2",
        "httpx",
        "jira",
        "requests",
        "smtplib",
        "socket",
        "telnetlib",
        "urllib3",
        "websocket",
        "websockets",
        "xmlrpc",
    }
)

# `urllib.parse` is pure string handling and is fine anywhere; `urllib.request`
# is not. Sub-module precision matters here.
NETWORK_SUBMODULES = frozenset({"urllib.request", "urllib.error", "http.client"})


@dataclass(frozen=True)
class Import:
    module: str
    file: Path
    line: int
    lazy: bool

    @property
    def where(self) -> str:
        return f"{self.file.relative_to(REPO_ROOT).as_posix()}:{self.line}"

    @property
    def root(self) -> str:
        return self.module.split(".")[0]


@dataclass(frozen=True)
class Call:
    dotted: str
    file: Path
    line: int

    @property
    def where(self) -> str:
        return f"{self.file.relative_to(REPO_ROOT).as_posix()}:{self.line}"


def module_files(layer: str | None = None) -> list[Path]:
    root = PACKAGE if layer is None else PACKAGE / layer
    return sorted(root.rglob("*.py")) if root.exists() else []


def module_name(path: Path) -> str:
    parts = path.relative_to(SRC).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _lazy_lines(tree: ast.AST) -> set[int]:
    """Line numbers inside a function body -- an import there is a lazy import."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Import | ast.ImportFrom):
                    lines.add(child.lineno)
    return lines


def imports_of(path: Path) -> list[Import]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lazy = _lazy_lines(tree)
    found: list[Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(Import(alias.name, path, node.lineno, node.lineno in lazy))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(Import(node.module, path, node.lineno, node.lineno in lazy))
    return found


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def attribute_uses(path: Path) -> list[Call]:
    """Every dotted name used, whether called or merely read (`os.environ`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and (dotted := _dotted(node)):
            found.append(Call(dotted, path, node.lineno))
    return found


def is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def is_network(module: str) -> bool:
    if module in NETWORK_SUBMODULES:
        return True
    return module.split(".")[0] in NETWORK_MODULES


def layer_of(path: Path) -> str | None:
    parts = path.relative_to(PACKAGE).parts
    return parts[0] if len(parts) > 1 and parts[0] in LAYERS else None
