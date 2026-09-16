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
    """Two statuses are exempt, and both are explicit rather than silent.

    `NOT MET` is the spec running ahead of the code. `SUPERSEDED` is it running
    behind on purpose — the rule is kept for its id and its history, and the
    test that proved it has gone or been reclaimed by its replacement.
    """
    if not rule.needs_a_living_test:
        return
    missing = [path for path in rule.proved_by if not (REPO_ROOT / path).exists()]
    assert not missing, (
        f"{rule.where}: status {rule.status} but these do not exist: {missing}. "
        "Either write the test, or set the status back to NOT MET."
    )


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_a_superseded_rule_names_a_replacement_that_exists(rule: Rule):
    """The alternative is a rule that silently contradicts another one.

    Renumbering is not available -- ids are referenced by test filenames and by
    other rules -- so a rule that stops being true is retired in place and must
    say what replaced it. `SUPERSEDED by R9.9` pointing at nothing is the same
    dangling reference the format exists to prevent.
    """
    if rule.status != "SUPERSEDED":
        return
    assert rule.superseded_by, (
        f"{rule.where}: status SUPERSEDED must read `SUPERSEDED by R<spec>.<rule>`, "
        "naming the rule that replaced it."
    )
    known = {other.id for other in RULES}
    assert rule.superseded_by in known, (
        f"{rule.where}: superseded by {rule.superseded_by}, which does not exist."
    )
    assert rule.superseded_by != rule.id, f"{rule.where}: a rule cannot supersede itself."


@pytest.mark.parametrize("rule", RULES, ids=_ids(RULES))
def test_a_supersession_points_at_a_rule_still_in_force(rule: Rule):
    """A reader following the trail must land on the rule that is true today.

    Two retirements of the same behaviour would otherwise chain, and the second
    hop is exactly where someone stops reading and implements the dead rule.
    """
    if rule.status != "SUPERSEDED":
        return
    replacement = next((r for r in RULES if r.id == rule.superseded_by), None)
    assert replacement is None or replacement.status != "SUPERSEDED", (
        f"{rule.where}: superseded by {rule.superseded_by}, which is itself "
        f"superseded by {replacement.superseded_by if replacement else '?'}. "
        "Point at the rule that is actually in force."
    )


def test_at_most_one_rule_is_in_progress():
    """One outer loop at a time. Two open slices is how neither gets finished."""
    in_progress = [rule for rule in RULES if rule.status == "IN PROGRESS"]
    assert len(in_progress) <= 1, "more than one rule is IN PROGRESS: " + ", ".join(
        rule.where for rule in in_progress
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
        assert not marked, f"{marked} carries @{OUTER_LOOP_MARKER} but no rule is IN PROGRESS."
        return
    # The acceptance-tier entries only. An open slice names its red acceptance
    # test from the start and gains a unit test per inner cycle, and those
    # must join the default suite as they land rather than wait behind the
    # marker -- otherwise the default suite never runs what /tdd just proved.
    expected = sorted(
        entry for entry in in_progress[0].proved_by if entry.startswith("tests/acceptance/")
    )
    assert expected, (
        f"{in_progress[0].where} is IN PROGRESS but names no tests/acceptance/ test; an "
        "outer loop is an acceptance test by definition."
    )
    assert marked == expected, (
        f"{in_progress[0].where} is IN PROGRESS and its acceptance tests are {expected}, "
        f"but the @{OUTER_LOOP_MARKER} marker is on {marked}."
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
    superseded = sum(1 for rule in RULES if rule.status == "SUPERSEDED")
    evaluated = sum(1 for rule in RULES if rule.kind == "evaluated")
    not_met = total - met - in_progress - superseded
    specs = len({rule.spec_file for rule in RULES})
    with capsys.disabled():
        print(
            f"\nspecs: {total} rules across {specs} specs | "
            f"{met} MET, {in_progress} IN PROGRESS, {not_met} NOT MET, "
            f"{superseded} SUPERSEDED | "
            f"{total - evaluated} deterministic, {evaluated} evaluated"
        )
    assert total > 0


def _declared_status(spec_file: Path) -> str | None:
    """The `**Status:**` line in a spec's header, above its first rule."""
    header = spec_file.read_text(encoding="utf-8").split("\n### ", 1)[0]
    found = re.search(r"^\*\*Status:\*\*\s*(.+)$", header, re.MULTILINE)
    return found.group(1).strip() if found else None


def _implied_status(rules: list[Rule]) -> str:
    """What a spec's own rules say about it, per the table in specs/README.md.

    Superseded rules are left out of the count entirely. They are retired, not
    outstanding, and a spec whose every live rule is built is `Implemented` even
    if it retired one on the way.
    """
    live = [rule for rule in rules if rule.status != "SUPERSEDED"]
    met = sum(1 for rule in live if rule.status == "MET")
    if live and met == len(live):
        return "Implemented"
    return "Partially implemented" if met else "Proposed"


@pytest.mark.parametrize(
    "spec_file",
    sorted({rule.spec_file for rule in RULES}),
    ids=lambda path: path.name,
)
def test_a_spec_declares_the_status_its_rules_imply(spec_file: Path):
    """A spec that misdescribes itself is the one document nobody can check against.

    The header is the first thing read and the last thing updated, so it drifts
    silently: eight specs sat at `Proposed` -- "written, not built" -- while five
    of them had rules `MET`. Deriving the answer from the rules makes the header
    a consequence of the work rather than a note about it.
    """
    rules = [rule for rule in RULES if rule.spec_file == spec_file]
    implied = _implied_status(rules)

    assert _declared_status(spec_file) == implied, (
        f"{as_repo_path(spec_file)} declares "
        f"{_declared_status(spec_file)!r} but its rules imply {implied!r}. "
        "See the status table in specs/README.md."
    )
