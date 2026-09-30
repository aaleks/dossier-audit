"""Mutation testing over `src/dossier/domain`, in hours rather than days.

    python dev/mutation/mutate.py init
    python dev/mutation/mutate.py run [--workers N] [--cap N] [--only web.py:137 ...]
    python dev/mutation/mutate.py report

`init` lists every mutant cosmic-ray would make, keeps the ones a test could
see, and records which tests execute each line. `run` tries each mutant against
those tests only, in parallel copies of the repository, and appends to
`results.jsonl`, so a stopped run resumes where it left off. `report` prints
what survived, with the line each mutant changed. dev/mutation/README.md says
why it is built this way and how to read a survivor.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIERS = ("unit", "acceptance", "integration")
COPY_IGNORES = (".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".env")

# Operators whose survivors were never observable in the first run (2026-09-30),
# skipped before they cost a test run: `*,` in a signature made `/,`, a
# dataclass's `frozen=True` made `False`, and `==` swapped with `is` on
# interned strings and enums.
IDENTITY = {
    "ReplaceComparisonOperator_Eq_Is",
    "ReplaceComparisonOperator_NotEq_IsNot",
    "ReplaceComparisonOperator_Is_Eq",
    "ReplaceComparisonOperator_IsNot_NotEq",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--work",
        type=Path,
        default=Path(tempfile.gettempdir()) / "dossier-mutation",
        help="where the copies, the coverage map and the results go (default: %(default)s)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="list the mutants and map each line to its tests")
    run = commands.add_parser("run", help="try every mutant not yet tried")
    run.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    run.add_argument(
        "--cap",
        type=int,
        default=120,
        help="the most tests one mutant runs, unit tests first; 0 for no cap (default: 120)",
    )
    run.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="MODULE[:LINE]",
        help="try these again, tried or not: a line, e.g. scoring.py:545, or a module",
    )
    run.add_argument(
        "--suite",
        action="store_true",
        help="run the whole default suite for each mutant, not its selection: for a"
        " handful, after tests were added that the coverage map has not seen",
    )
    run.add_argument("--timeout", type=int, default=1800, help="seconds a mutant may take")
    commands.add_parser("report", help="print the survivors")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    {"init": init, "run": run_mutants, "report": report}[args.command](args)


# -- init ------------------------------------------------------------------------------


def init(args: argparse.Namespace) -> None:
    work: Path = args.work
    (work / "results.jsonl").unlink(missing_ok=True)
    copy = fresh_copy(work, 0)
    print("mapping lines to tests: the default suite under coverage, once", flush=True)
    rc = work / "coveragerc"
    rc.write_text(
        "[run]\n"
        f"source = {domain_path().as_posix()}\n"
        "dynamic_context = test_function\n"
        f"data_file = {(work / 'coverage.data').as_posix()}\n",
        encoding="utf-8",
    )
    (work / "coverage.data").unlink(missing_ok=True)
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--rcfile={rc}", "-m", "pytest", "-q"]
        + ["-p", "no:cacheprovider", f"--basetemp={work / 'b0'}"]
        + [f"tests/{tier}" for tier in TIERS],
        cwd=copy,
        env=test_env(copy),
    )
    if done.returncode != 0:
        sys.exit("the suite is not green; a mutant killed by a failing test proves nothing")
    print(f"  {time.monotonic() - started:.0f} s", flush=True)

    mutants, dropped = [], Counter()
    # Mutants and hashes from the copy the coverage map was made in, so the
    # two agree on every line number even if the repository moved meanwhile.
    for module in modules(copy):
        kept, skipped = module_mutants(module, copy)
        mutants += kept
        dropped += skipped
    (work / "mutants.json").write_text(
        json.dumps({"sources": source_hashes(copy), "mutants": mutants}, indent=1),
        encoding="utf-8",
    )
    print(f"{len(mutants)} mutants to run; dropped {dict(sorted(dropped.items()))}")


def module_mutants(module: str, root: Path) -> tuple[list[dict], Counter]:
    """Every mutant of `module` a test could see, and a count of the ones dropped."""
    from cosmic_ray.ast import ast_nodes, get_ast_from_path
    from cosmic_ray.mutating import mutate_code
    from cosmic_ray.plugins import get_operator, operator_names

    source = (root / module).read_text(encoding="utf-8")
    lines = source.splitlines()
    base = without_annotations(ast.parse(source))
    tree = get_ast_from_path(root / module)
    kept, dropped = [], Counter()
    for name in operator_names():
        operator_class = get_operator(name)
        if operator_class.arguments():
            continue  # none is configured, so cosmic-ray itself would make none
        operator = operator_class()
        positions = [
            (start, end)
            for node in ast_nodes(tree)
            for start, end in operator.mutation_positions(node)
        ]
        short = name.split("/")[-1]
        for occurrence, (start, end) in enumerate(positions):
            try:
                mutated = mutate_code(source, operator, occurrence)
            except Exception:  # ExceptionReplacer on a dotted name, as of cosmic-ray 8.7
                dropped["cosmic-ray cannot apply"] += 1
                continue
            if mutated is None or mutated == source:
                dropped["no-op"] += 1
                continue
            try:
                changed = ast.parse(mutated)
            except SyntaxError:
                dropped["does not compile"] += 1
                continue
            # Every domain module has `from __future__ import annotations`, so
            # `str | None` made `str & None` changes nothing a test can see.
            if without_annotations(changed) == base:
                dropped["annotation only"] += 1
                continue
            if noise(short, lines[start[0] - 1]):
                dropped["never observable"] += 1
                continue
            kept.append(
                {
                    "id": f"{Path(module).name}:{start[0]}:{short}#{occurrence}",
                    "module": module,
                    "operator": name,
                    "occurrence": occurrence,
                    "start": start[0],
                    "end": end[0],
                }
            )
    return kept, dropped


def noise(operator: str, line: str) -> bool:
    if operator == "ReplaceBinaryOperator_Mul_Div" and ("*," in line or "*)" in line):
        return True
    if operator in IDENTITY:
        return True
    return operator == "ReplaceTrueWithFalse" and "frozen=" in line


def without_annotations(tree: ast.AST) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            node.annotation = None
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            node.returns = None
        if isinstance(node, ast.TypeAlias):
            # `type Failure = tuple[str, str, str | None]` is evaluated only if
            # something asks for its value, and nothing at run time does.
            node.value = ast.Constant(None)
        if isinstance(node, ast.AnnAssign):
            node.annotation = ast.Constant(None)
    return ast.dump(tree)


# -- run -------------------------------------------------------------------------------


def run_mutants(args: argparse.Namespace) -> None:
    work: Path = args.work
    plan = json.loads((work / "mutants.json").read_text(encoding="utf-8"))
    results = read_results(work)
    mutants = plan["mutants"]
    if args.only:
        wanted = set(args.only)
        mutants = [
            m
            for m in mutants
            if {Path(m["module"]).name, f"{Path(m['module']).name}:{m['start']}"} & wanted
        ]
    else:
        mutants = [m for m in mutants if m["id"] not in results]
    now = source_hashes()
    moved = sorted(
        {m["module"] for m in mutants if plan["sources"][m["module"]] != now.get(m["module"])}
    )
    if moved:
        # A mutant is an occurrence counted in the source init read. Against
        # another source it is another mutant, or none.
        sys.exit(f"changed since init: {', '.join(moved)}. Run init again.")
    selector = None if args.suite else Selector(work)
    print(f"{len(mutants)} to run on {args.workers} copies", flush=True)

    copies: queue.Queue = queue.Queue()
    for k in range(args.workers):
        copies.put((k, fresh_copy(work, k)))
    lock = threading.Lock()
    counter = iter(range(1, len(mutants) + 1))

    def one(mutant: dict) -> None:
        k, copy = copies.get()
        try:
            entry = try_mutant(mutant, copy, work / f"b{k}", selector, args)
        except Exception as error:  # a crash is one mutant's result, not a stopped run
            entry = {"id": mutant["id"], "outcome": "error", "error": repr(error)}
        finally:
            copies.put((k, copy))
        with lock:
            with (work / "results.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(entry) + "\n")
            done = f"[{next(counter)}/{len(mutants)}]"
            print(f"{done} {entry['id']}: {entry['outcome']}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(one, mutants))


def try_mutant(
    mutant: dict, copy: Path, basetemp: Path, selector: Selector | None, args
) -> dict:
    from cosmic_ray.mutating import mutate_code
    from cosmic_ray.plugins import get_operator

    entry = {"id": mutant["id"]}
    if selector is None:
        kind, tests = "suite", [f"tests/{tier}" for tier in TIERS]
    else:
        kind, tests = selector.tests_for(mutant)
    entry.update(selection=kind, tests=len(tests))
    if kind == "uncovered":
        return entry | {"outcome": "survived"}
    # A survivor runs every test it selected, and past a hundred or so that is
    # minutes a mutant. Unit tests come first, so a capped run keeps the fast,
    # precise ones; a capped survivor is tried again with --cap 0 before
    # anything is written for it.
    if args.cap and len(tests) > args.cap:
        tests = tests[: args.cap]
        entry.update(capped=True, ran=args.cap)

    target = copy / mutant["module"]
    original = target.read_bytes()
    source = original.decode("utf-8")
    mutated = mutate_code(source, get_operator(mutant["operator"])(), mutant["occurrence"])
    listed = basetemp.with_suffix(".args")
    listed.write_text("\n".join(tests), encoding="utf-8")
    started = time.monotonic()
    try:
        target.write_bytes(mutated.encode("utf-8"))
        forget_compiled(target)
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"]
            + [f"--basetemp={basetemp}", f"@{listed}"],
            cwd=copy,
            env=test_env(copy),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
        )
        code = done.returncode
    except subprocess.TimeoutExpired:
        code, done = None, None
    finally:
        target.write_bytes(original)
        forget_compiled(target)
    entry["took"] = round(time.monotonic() - started, 1)
    if code is None:
        return entry | {"outcome": "timeout"}
    if code == 0:
        return entry | {"outcome": "survived"}
    failed = [line for line in done.stdout.splitlines() if line.startswith("FAILED")]
    if code == 1:
        return entry | {"outcome": "killed", "killer": failed[0] if failed else ""}
    # 2 to 5: interrupted, an internal error, a usage error, nothing collected.
    return entry | {"outcome": "error", "error": done.stdout[-1500:]}


class Selector:
    """Which tests execute a mutant's lines, from the coverage map `init` made."""

    def __init__(self, work: Path) -> None:
        import coverage

        files: dict[str, str] = {}
        for tier in TIERS:
            for path in (ROOT / "tests" / tier).glob("test_*.py"):
                files[path.stem] = f"tests/{tier}/{path.name}"
        data = coverage.CoverageData(basename=str(work / "coverage.data"))
        data.read()
        copy = work / "c0"
        self.lines: dict[str, dict[int, set[str]]] = {}
        self.everything: dict[str, set[str]] = {}
        self.at_import: dict[str, set[int]] = {}
        for measured in data.measured_files():
            module = Path(measured).relative_to(copy).as_posix()
            self.lines[module], self.everything[module] = {}, set()
            self.at_import[module] = set()
            for line, contexts in data.contexts_by_lineno(measured).items():
                tests = {self.node_id(c, files) for c in contexts if c}
                tests.discard(None)
                self.lines[module][line] = tests
                self.everything[module] |= tests
                if "" in contexts:
                    self.at_import[module].add(line)
        self.functions: dict[str, list[ast.AST]] = {}

    @staticmethod
    def node_id(context: str, files: dict[str, str]) -> str | None:
        """`test_R001_29__x.TestY.test_z` as the node id pytest takes."""
        module, *rest = context.split(".")
        return "::".join([files[module], *rest]) if module in files else None

    def tests_for(self, mutant: dict) -> tuple[str, list[str]]:
        module = mutant["module"]
        lines = range(mutant["start"], mutant["end"] + 1)
        by_line = self.lines.get(module, {})
        tests = set().union(*(by_line.get(n, set()) for n in lines))
        if tests:
            return "line", ordered(tests)
        if any(n in self.at_import.get(module, set()) for n in lines):
            # Run once, at import: every test that imported the module.
            return "module", ordered(self.everything[module])
        # A line inside a signature that spans lines is never recorded as run;
        # its mutant is killed, if at all, by what calls the function.
        for function in self.functions_of(module):
            if function.lineno <= mutant["start"] < function.body[0].lineno:
                body = range(function.body[0].lineno, function.end_lineno + 1)
                tests = set().union(*(by_line.get(n, set()) for n in body))
                return ("signature", ordered(tests)) if tests else ("uncovered", [])
        return "uncovered", []

    def functions_of(self, module: str) -> list[ast.AST]:
        if module not in self.functions:
            tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
            self.functions[module] = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
        return self.functions[module]


def ordered(tests: set[str]) -> list[str]:
    return sorted(tests, key=lambda test: (TIERS.index(test.split("/")[1]), test))


# -- report ----------------------------------------------------------------------------


def report(args: argparse.Namespace) -> None:
    from cosmic_ray.mutating import mutate_code
    from cosmic_ray.plugins import get_operator

    plan = json.loads((args.work / "mutants.json").read_text(encoding="utf-8"))
    results = read_results(args.work)
    outcomes = Counter(entry["outcome"] for entry in results.values())
    print(f"{len(results)} of {len(plan['mutants'])} tried: {dict(sorted(outcomes.items()))}")
    now = source_hashes()
    for mutant in plan["mutants"]:
        entry = results.get(mutant["id"])
        if entry is None or entry["outcome"] == "killed":
            continue
        notes = [entry["outcome"]]
        if entry.get("capped"):
            notes.append(f"ran {entry['ran']} of {entry['tests']} tests; try --cap 0")
        if entry.get("selection") == "uncovered":
            notes.append("no test runs this line")
        print(f"\n{mutant['id']}  ({', '.join(notes)})")
        if now.get(mutant["module"]) != plan["sources"][mutant["module"]]:
            print("  (the module changed since init: run init again to see the line)")
            continue
        source = (ROOT / mutant["module"]).read_text(encoding="utf-8")
        mutated = mutate_code(source, get_operator(mutant["operator"])(), mutant["occurrence"])
        for line in difflib.unified_diff(
            source.splitlines(), mutated.splitlines(), n=0, lineterm=""
        ):
            if line.startswith(("-", "+")) and not line.startswith(("---", "+++")):
                print(f"  {line}")


# -- shared ----------------------------------------------------------------------------


def config() -> dict:
    return tomllib.loads((ROOT / "mutation.toml").read_text(encoding="utf-8"))["cosmic-ray"]


def domain_path() -> Path:
    return Path(config()["module-path"])


def modules(root: Path = ROOT) -> list[str]:
    excluded = set(config().get("excluded-modules", []))
    return [
        path.relative_to(root).as_posix()
        for path in sorted((root / domain_path()).glob("*.py"))
        if path.relative_to(root).as_posix() not in excluded
    ]


def source_hashes(root: Path = ROOT) -> dict[str, str]:
    return {m: hashlib.sha256((root / m).read_bytes()).hexdigest() for m in modules(root)}


def read_results(work: Path) -> dict[str, dict]:
    """The latest result for each mutant: `--only` appends, and the last one stands."""
    path = work / "results.jsonl"
    if not path.exists():
        return {}
    entries = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {entry["id"]: entry for entry in entries}


def fresh_copy(work: Path, k: int) -> Path:
    """A copy of the repository as it is now, to mutate without touching it."""
    copy = work / f"c{k}"
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(*COPY_IGNORES))
    return copy


def forget_compiled(module: Path) -> None:
    for stale in (module.parent / "__pycache__").glob(f"{module.stem}.*.pyc"):
        stale.unlink()


def test_env(copy: Path) -> dict[str, str]:
    # The copy's src comes first (pyproject's `pythonpath` says so too), and no
    # bytecode is written: a stale .pyc of a mutant is a mutant run twice.
    return dict(
        os.environ,
        PYTHONPATH=str(copy / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )


if __name__ == "__main__":
    main()
