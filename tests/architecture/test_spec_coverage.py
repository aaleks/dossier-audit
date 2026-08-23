"""Do the specs and the tests still refer to each other?

This is the mechanical half of the working agreement. It cannot tell you whether
a test *proves* its rule -- that judgement is `/verify` and the `spec-compliance`
agent. It can tell you that a rule was written and never built, that a test was
written and nothing claims it, and that a rule's shape is not checkable.

Each failure below is deliberate and each means something different. The message
says which.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .spec_parser import (
    CLAIMED_TIERS,
    REPO_ROOT,
    TEST_FILE_RE,
    VALID_KINDS,
    VALID_STATUSES,
    Rule,
    as_repo_path,
    claimable_test_files,
    load_rules,
)

RULES = load_rules()
OUTER_LOOP_MARKER = "pytest.mark.outer_loop"


def _ids(rules: list[Rule]) -> list[str]:
    return [rule.id for rule in rules]


def test_specs_contain_rules():
    """A spec set that parses to nothing would make every check below vacuous."""
    assert RULES, "no rules parsed out of specs/ -- check the ### R<n>.<m> heading format"


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_every_rule_declares_a_kind(rule: Rule):
    """`deterministic` gets an exact test; `evaluated` gets a threshold."""
    assert rule.kind in VALID_KINDS, (
        f"{rule.where}: Kind is {rule.kind!r}, expected one of {sorted(VALID_KINDS)}. "
        "Without it, nobody can tell whether this rule wants pytest or a judge."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_every_rule_declares_a_layer(rule: Rule):
    """A rule with no layer is a rule nobody has decided where to put."""
    assert rule.layer, f"{rule.where}: no **Layer:** line. See docs/architecture.md."


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_every_rule_declares_a_status(rule: Rule):
    assert rule.status in VALID_STATUSES, (
        f"{rule.where}: Status is {rule.status!r}, expected one of {sorted(VALID_STATUSES)}."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_every_rule_names_a_test(rule: Rule):
    """The test need not exist yet. Naming it is what stops a spec drifting free."""
    assert rule.proved_by, (
        f"{rule.where}: **Proved by:** names no `tests/...` path. "
        "Name the test you would write, even before it exists."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_evaluated_rules_carry_a_threshold(rule: Rule):
    """A number you invented becomes a gate. OPEN is honest; silence is not."""
    if rule.kind != "evaluated":
        return
    assert rule.threshold, (
        f"{rule.where}: an `evaluated` rule needs a **Threshold:** -- a number and who "
        "agreed it, or OPEN with what would resolve it."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_deterministic_rules_carry_no_threshold(rule: Rule):
    """A threshold on a deterministic rule means it was misclassified."""
    if rule.kind != "deterministic":
        return
    assert not rule.threshold, (
        f"{rule.where}: a deterministic rule has a threshold. Either it is really "
        "`evaluated`, or the threshold belongs to a different rule."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_every_rule_has_examples(rule: Rule):
    """A rule with no example is not understood yet."""
    assert len(rule.example_rows) >= 2, (
        f"{rule.where}: {len(rule.example_rows)} example row(s). A rule needs concrete "
        "cases with real values -- they are the test cases."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_every_rule_has_a_counter_example(rule: Rule):
    """Where the rule deliberately does not apply. Usually where the boundary is."""
    assert rule.counter_examples, (
        f"{rule.where}: no row marked *counter-example*. A rule with only positive "
        "examples is usually a truism, or two rules."
    )


def test_rule_ids_are_unique():
    seen: dict[str, Rule] = {}
    duplicates = []
    for rule in RULES:
        if rule.id in seen:
            duplicates.append(f"{rule.id}: {seen[rule.id].where} and {rule.where}")
        seen[rule.id] = rule
    assert not duplicates, "duplicate rule ids -- tests reference these:\n" + "\n".join(
        duplicates
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_rule_id_matches_its_spec_number(rule: Rule):
    file_number = int(rule.spec_file.name[:3])
    assert rule.spec_number == file_number, (
        f"{rule.where}: rule id says spec {rule.spec_number}, file is {file_number}."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_a_met_rule_names_a_test_that_exists(rule: Rule):
    """`NOT MET` is exempt. That exemption is the only one, and it is explicit."""
    if rule.status == "NOT MET":
        return
    missing = [path for path in rule.proved_by if not (REPO_ROOT / path).exists()]
    assert not missing, (
        f"{rule.where}: status {rule.status} but these do not exist: {missing}. "
        "Either write the test, or set the status back to NOT MET."
    )


def test_at_most_one_rule_is_in_progress():
    """One outer loop at a time. Two open slices is how neither gets finished."""
    in_progress = [rule for rule in RULES if rule.status == "IN PROGRESS"]
    assert len(in_progress) <= 1, (
        "more than one rule is IN PROGRESS: "
        + ", ".join(rule.where for rule in in_progress)
    )


def test_the_in_progress_rule_owns_the_outer_loop_test():
    """The open rule and the red acceptance test must be the same thing."""
    in_progress = [rule for rule in RULES if rule.status == "IN PROGRESS"]
    # Scanned over the behavioural tiers only. An outer loop is an acceptance
    # test by definition, and tests/architecture holds this checker, whose own
    # source mentions the marker by name.
    marked = sorted(
        as_repo_path(path)
        for tier in CLAIMED_TIERS
        for path in (REPO_ROOT / "tests" / tier).rglob("test_*.py")
        if OUTER_LOOP_MARKER in path.read_text(encoding="utf-8")
    )
    if not in_progress:
        assert not marked, (
            f"{marked} carries @{OUTER_LOOP_MARKER} but no rule is IN PROGRESS."
        )
        return
    expected = sorted(in_progress[0].proved_by)
    assert marked == expected, (
        f"{in_progress[0].where} is IN PROGRESS and names {expected}, but the "
        f"@{OUTER_LOOP_MARKER} marker is on {marked}."
    )


@pytest.mark.parametrize(
    "path", claimable_test_files(), ids=lambda p: p.name if isinstance(p, Path) else str(p)
)
def test_every_test_file_is_named_by_a_rule(path: Path):
    """An unclaimed test is behaviour nobody agreed to."""
    claimed = {entry for rule in RULES for entry in rule.proved_by}
    assert as_repo_path(path) in claimed, (
        f"{as_repo_path(path)} is claimed by no rule's **Proved by:** line. "
        "Add it to the rule it proves, or delete it."
    )


@pytest.mark.parametrize(
    "path", claimable_test_files(), ids=lambda p: p.name if isinstance(p, Path) else str(p)
)
def test_every_test_file_is_named_after_a_rule_id(path: Path):
    """`test_R002_5__second_sync_fetches_nothing.py` -- the id links spec to test."""
    assert TEST_FILE_RE.match(path.name), (
        f"{as_repo_path(path)}: expected test_R<spec>_<rule>__<description>.py, "
        "for example test_R002_5__second_sync_fetches_nothing.py"
    )


def test_no_rule_references_a_test_outside_the_tests_tree():
    stray = [
        f"{rule.where}: {path}"
        for rule in RULES
        for path in rule.proved_by
        if not re.match(r"^tests/[a-z]+/", path)
    ]
    assert not stray, "Proved by must name a path under tests/<tier>/:\n" + "\n".join(stray)


def test_coverage_summary_is_reportable(capsys):
    """Not an assertion about the code. A number `/quality` and `/verify` quote."""
    total = len(RULES)
    met = sum(1 for rule in RULES if rule.status == "MET")
    in_progress = sum(1 for rule in RULES if rule.status == "IN PROGRESS")
    evaluated = sum(1 for rule in RULES if rule.kind == "evaluated")
    with capsys.disabled():
        print(
            f"\nspecs: {total} rules across 8 specs | "
            f"{met} MET, {in_progress} IN PROGRESS, {total - met - in_progress} NOT MET | "
            f"{total - evaluated} deterministic, {evaluated} evaluated"
        )
    assert total > 0
