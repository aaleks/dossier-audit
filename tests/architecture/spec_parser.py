"""Parse the rule blocks out of `specs/`.

Shared by the architecture tests and by nothing else. It is deliberately strict:
a rule that does not parse is a rule the checker cannot enforce, and silently
skipping it would make the whole mechanism decorative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "specs"
TESTS_DIR = REPO_ROOT / "tests"

VALID_KINDS = {"deterministic", "evaluated"}
VALID_STATUSES = {"NOT MET", "IN PROGRESS", "MET", "SUPERSEDED"}

# A rule is never renumbered and never deleted -- test filenames and other rules
# reference its id. When it stops being true it is superseded, in place, and says
# by what: `**Status:** SUPERSEDED by R2.10`.
SUPERSEDED_RE = re.compile(r"^SUPERSEDED by (R\d+\.\d+)$")

# Test tiers whose every file must be named by a rule. tests/architecture is
# excluded as a directory because it also holds the checker itself; files there
# named test_R<spec>_<rule>__ are still claimed, via TEST_FILE_RE below.
CLAIMED_TIERS = ("unit", "acceptance", "integration", "evals")

TEST_FILE_RE = re.compile(r"^test_R(\d{3})_(\d+)__[a-z0-9_]+\.py$")

_RULE_HEADING_RE = re.compile(r"^### (R(\d+)\.(\d+))\s+[-–—]\s+(.+)$")
_FIELD_RE = r"^- \*\*{name}:\*\*\s*(.+)$"
_BACKTICKED_RE = re.compile(r"`([^`]+)`")
_TABLE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|(.+)\|\s*$")


@dataclass
class Rule:
    id: str
    spec_number: int
    rule_number: int
    title: str
    spec_file: Path
    line: int
    body: str
    kind: str | None = None
    layer: str | None = None
    status: str | None = None
    threshold: str | None = None
    superseded_by: str | None = None
    proved_by: list[str] = field(default_factory=list)
    example_rows: list[str] = field(default_factory=list)

    @property
    def needs_a_living_test(self) -> bool:
        """`NOT MET` is the spec running ahead of the code; `SUPERSEDED` is it
        running behind, on purpose. Both are exempt from naming a test that
        exists -- and both say so explicitly, which is the point."""
        return self.status not in ("NOT MET", "SUPERSEDED")

    @property
    def where(self) -> str:
        return f"{self.spec_file.name}:{self.line} ({self.id})"

    @property
    def counter_examples(self) -> list[str]:
        return [row for row in self.example_rows if "counter-example" in row.lower()]


def _field_value(body: str, name: str) -> str | None:
    match = re.search(_FIELD_RE.format(name=name), body, re.MULTILINE)
    return match.group(1).strip() if match else None


def _parse_spec(path: Path) -> list[Rule]:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = _RULE_HEADING_RE.match(line)
        if match:
            starts.append((index, match))

    rules: list[Rule] = []
    for position, (index, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        # A rule block ends at the next rule or the next top-level section.
        for offset in range(index + 1, end):
            if lines[offset].startswith("## "):
                end = offset
                break
        body = "\n".join(lines[index:end])

        rule = Rule(
            id=match.group(1),
            spec_number=int(match.group(2)),
            rule_number=int(match.group(3)),
            title=match.group(4).strip(),
            spec_file=path,
            line=index + 1,
            body=body,
            kind=_field_value(body, "Kind"),
            layer=_field_value(body, "Layer"),
            status=_field_value(body, "Status"),
            threshold=_field_value(body, "Threshold"),
        )

        # `SUPERSEDED by R2.10` carries its replacement in the status line, so the
        # link is visible where the status is read rather than in a separate field
        # someone can forget to update.
        if rule.status and (superseded := SUPERSEDED_RE.match(rule.status)):
            rule.superseded_by = superseded.group(1)
            rule.status = "SUPERSEDED"

        proved = _field_value(body, "Proved by") or ""
        rule.proved_by = [
            candidate
            for candidate in _BACKTICKED_RE.findall(proved)
            if candidate.startswith("tests/")
        ]
        rule.example_rows = [
            row_match.group(2)
            for line_text in body.splitlines()
            if (row_match := _TABLE_ROW_RE.match(line_text.strip()))
        ]
        rules.append(rule)
    return rules


def load_rules() -> list[Rule]:
    """Every rule in every numbered spec, in spec then rule order."""
    rules: list[Rule] = []
    for path in sorted(SPECS_DIR.glob("[0-9][0-9][0-9]-*.md")):
        rules.extend(_parse_spec(path))
    return rules


def claimable_test_files() -> list[Path]:
    """Test files that must be named by some rule's `Proved by:` line."""
    found: list[Path] = []
    for tier in CLAIMED_TIERS:
        tier_dir = TESTS_DIR / tier
        if tier_dir.exists():
            found.extend(p for p in tier_dir.rglob("test_*.py"))
    architecture_dir = TESTS_DIR / "architecture"
    if architecture_dir.exists():
        found.extend(p for p in architecture_dir.rglob("test_R*.py"))
    return sorted(found)


def as_repo_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()
