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

# The four packages permitted to reach the network (R0.19). Connectors fetch
# source payloads; model clients ask a model, for an answer or a vector; the
# tracker sends records to MLflow; the index sink writes the embedding index.
# Everything else is reproducible from frozen content, which is what the hash
# boundary promises -- and neither tracking nor the index feeds anything back
# into a key, a manifest or a score, so they change none of that.
CONNECTORS = "dossier.infrastructure.connectors"
MODELS = "dossier.infrastructure.models"
TRACKING = "dossier.infrastructure.tracking"
INDEX = "dossier.infrastructure.index"
REACH_THE_NETWORK = (CONNECTORS, MODELS, TRACKING, INDEX)

NETWORK_MODULES = frozenset(
    {
        "aiohttp",
        # Model SDKs. Absent until R0.9, which meant the check would have passed
        # green whatever a model client imported -- the one file it most needed
        # to see. A vendor SDK is a network client whatever it is named.
        "anthropic",
        "atlassian",
        "boto3",
        "ftplib",
        "http",
        "httpcore",
        "httplib2",
        "httpx",
        # Hugging Face's client downloads weights. Docling reaches for it on its
        # own, and `docling-markdown` passes Docling a model folder so that it
        # never does (R8.15); nothing in dossier imports it.
        "huggingface_hub",
        "cohere",
        "google",
        "jira",
        "litellm",
        "mistralai",
        # MLflow reaches a tracking server over HTTP. Uncounted under R0.9, so the
        # check would have stayed green while it was imported anywhere (R0.10).
        "mlflow",
        "ollama",
        "openai",
        # Postgres clients reach a database server. Counted from R0.16, which
        # admitted the index sink, so that the exemption has teeth: a psycopg
        # import anywhere else is a violation. `pgvector` is here because its
        # adapters exist only to talk to that server.
        "asyncpg",
        "pgvector",
        "psycopg",
        "psycopg2",
        "psycopg_pool",
        # A browser asks for whatever the page it draws asks for. Only the web
        # connector may drive one (R1.40, R0.10).
        "playwright",
        "requests",
        "smtplib",
        "socket",
        "telnetlib",
        "together",
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
            # `from urllib import request` names the module in the alias, not in
            # `node.module` -- recording only the latter left the whole
            # `from X import Y` form invisible to R0.1, which is the check every
            # other guarantee in this project leans on. Each submodule is
            # recorded too, so the pair is caught however it was spelled.
            for alias in node.names:
                found.append(
                    Import(
                        f"{node.module}.{alias.name}",
                        path,
                        node.lineno,
                        node.lineno in lazy,
                    )
                )
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
