"""R7.2 — results are reported per field, and never as an overall figure alone.

A field at 50% and a field at 100% need different work, and a blended 80.0%
hides which is which. The overall figure may be printed; it may never be all
that is printed.

No single component can make this true. Sync must hold the four documents, run
must extract and record their fields, and eval must read what the run recorded,
score it against the gold set (R7.1, R7.3) and print it per field. The gold set
is the one a person wrote into `tests/fixtures/gold/incidents/` from
`_fixtures.md`'s scoring example. It is read here, never written.

The documents come from an issue-tracker source rather than the fixture folder,
because a folder keys a document by its file name, `INC-4821.md`, while the gold
set is keyed by the document itself, `INC-4821` -- the key an issue tracker
reports.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes import NoModelClient, register_connector
from tests.pipelines import write_pipeline

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")

# R7.2 example 1, transcribed.
EXPECTED = {
    "loss_amount": "100.0%",
    "resolution_date": "75.0%",
    "severity": "100.0%",
    "affected_systems": "75.0%",
    "root_cause": "50.0%",
}

ISSUES = {
    "INC-4821": (
        "# INC-4821\n\n"
        "Finance confirmed a total exposure CHF 48'200 in late-settlement interest.\n"
        "Resolved on 2026-07-28.\n"
        "Severity was assessed as major.\n"
        "Affected systems: payments-api, ledger-batch.\n"
    ),
    "INC-4822": (
        "# INC-4822\n\n"
        "Finance confirmed a total exposure CHF 12'500.\n"
        "Resolved on 2026-08-04.\n"
        "Severity was assessed as minor.\n"
        "Affected systems: ledger-batch.\n"
        "An early guess was disk pressure on the batch host; nobody confirmed it.\n"
    ),
    "INC-4901": (
        "# INC-4901\n\n"
        "Finance confirmed a total exposure CHF 0.00.\n"
        "Resolved on 2026-08-11; the ticket was closed on 2026-08-12.\n"
        "Severity was assessed as critical.\n"
        "Affected systems: payments-api.\n"
    ),
    "INC-5455": (
        "# INC-5455\n\n"
        "Finance confirmed a total exposure CHF 3'100.\n"
        "Resolved on 2026-08-19.\n"
        "Severity was assessed as major.\n"
        "Affected systems: upload-service. payments-api was checked and ruled out.\n"
        "Root cause undetermined; the competing hypotheses include an unbounded "
        "retry loop.\n"
    ),
}


def _found(document: str, field: str, value, span: str, **extra) -> dict:
    return {
        "field": field,
        "value": value,
        **extra,
        "source": {"document": document, "span": span},
    }


def _abstains(field: str) -> dict:
    return {"field": field, "value": None, "reason": "not stated in document"}


# What the run answers: gold's value everywhere except the four disagreements
# `_fixtures.md` lists. Each answer cites a span its document really holds, so
# every verdict below is about the value and none is about grounding (R7.4).
ANSWERS = {
    "INC-4821": [
        _found(
            "INC-4821", "loss_amount", 48200.00, "total exposure CHF 48'200", currency="CHF"
        ),
        _found("INC-4821", "resolution_date", "2026-07-28", "Resolved on 2026-07-28"),
        _found("INC-4821", "severity", "major", "Severity was assessed as major"),
        _found(
            "INC-4821",
            "affected_systems",
            "payments-api, ledger-batch",
            "Affected systems: payments-api, ledger-batch",
        ),
        _abstains("root_cause"),
    ],
    "INC-4822": [
        _found(
            "INC-4822", "loss_amount", 12500.00, "total exposure CHF 12'500", currency="CHF"
        ),
        _found("INC-4822", "resolution_date", "2026-08-04", "Resolved on 2026-08-04"),
        _found("INC-4822", "severity", "minor", "Severity was assessed as minor"),
        _found(
            "INC-4822", "affected_systems", "ledger-batch", "Affected systems: ledger-batch"
        ),
        # Disagreement: gold abstains, the run took an unconfirmed guess as the cause.
        _found(
            "INC-4822",
            "root_cause",
            "disk pressure on the batch host",
            "disk pressure on the batch host",
        ),
    ],
    "INC-4901": [
        _found("INC-4901", "loss_amount", 0.00, "total exposure CHF 0.00", currency="CHF"),
        # Disagreement: the run read the date the ticket closed, not the resolution.
        _found(
            "INC-4901",
            "resolution_date",
            "2026-08-12",
            "the ticket was closed on 2026-08-12",
        ),
        _found("INC-4901", "severity", "critical", "Severity was assessed as critical"),
        _found(
            "INC-4901", "affected_systems", "payments-api", "Affected systems: payments-api"
        ),
        _abstains("root_cause"),
    ],
    "INC-5455": [
        _found("INC-5455", "loss_amount", 3100.00, "total exposure CHF 3'100", currency="CHF"),
        _found("INC-5455", "resolution_date", "2026-08-19", "Resolved on 2026-08-19"),
        _found("INC-5455", "severity", "major", "Severity was assessed as major"),
        # Disagreement: the run named the system that was ruled out.
        _found(
            "INC-5455",
            "affected_systems",
            "payments-api",
            "payments-api was checked and ruled out",
        ),
        # Disagreement: gold abstains, the run picked one competing hypothesis.
        _found("INC-5455", "root_cause", "an unbounded retry loop", "an unbounded retry loop"),
    ],
}


class IssueTracker:
    """A source keyed by incident, as an issue tracker is. No network, no markers."""

    media_type = "text/markdown"

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(ISSUES):
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(
            key=key,
            payload=ISSUES[key].encode("utf-8"),
            media_type=self.media_type,
            remote_version=None,
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class RoutedModel:
    """A model client answering each document with its own scripted answer.

    Routed by the document in the prompt rather than consumed in order, so the
    test does not depend on the order a run visits documents in. It counts calls,
    because "one extraction per document" is a claim about how many happened.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        asked = [key for key in ANSWERS if f"# {key}\n" in prompt]
        assert len(asked) == 1, f"expected one document in the prompt, found {asked}"
        self.calls.append(asked[0])
        return json.dumps({"document": asked[0], "fields": ANSWERS[asked[0]]})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _eval(workspace: Path, monkeypatch, gold: str = "gold/incidents"):
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", gold)


def _field_lines(output: str) -> dict[str, str]:
    """Each field's line in the report, by the field name it starts with."""
    lines: dict[str, str] = {}
    for line in output.splitlines():
        words = line.split()
        if words and words[0] in FIELDS:
            lines[words[0]] = line
    return lines


def _percentage(line: str) -> str | None:
    found = re.search(r"\d+\.\d%", line)
    return found.group() if found else None


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """A workspace where the four documents are synced and run through `extract`."""
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker())

    model = RoutedModel()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    assert model.call_count == 4, "one extraction per document"

    # Scoring asks no model: every field here is scored without a judge (R7.10),
    # root_cause included, because its gold is null throughout (R7.3).
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return workspace


class TestScoresAreReportedPerField:
    """R7.2 — results are reported per field, and never as an overall figure alone."""

    def test_every_declared_field_is_listed_with_its_own_percentage(
        self, audited: Path, monkeypatch
    ):
        """Example 1: the one where each of the five fields gets its own number."""
        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        lines = _field_lines(result.output)
        assert {field: _percentage(lines.get(field, "")) for field in FIELDS} == EXPECTED

    def test_the_overall_figure_never_stands_without_the_breakdown(
        self, audited: Path, monkeypatch
    ):
        """Example 2: the one where 80.0% may be printed, but never on its own.

        16 of 20 is what the five fields add up to, and a report that printed it
        without them would hide root_cause's 50.0% behind it.
        """
        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        overall = [line for line in result.output.splitlines() if "overall" in line]
        assert all("80.0%" in line for line in overall), overall
        assert set(_field_lines(result.output)) == set(FIELDS)

    def test_the_weakest_field_is_marked(self, audited: Path, monkeypatch):
        """Example 3: the one where root_cause, at 50.0%, is marked as the weakest."""
        result = _eval(audited, monkeypatch)

        assert result.exit_code == 0, result.output
        lines = _field_lines(result.output)
        assert [field for field, line in lines.items() if "weakest" in line] == ["root_cause"]

    def test_a_gold_set_covering_one_field_still_lists_that_field(
        self, audited: Path, monkeypatch
    ):
        """Counter-example (row 4): the one where gold covers severity alone.

        The rule is about never collapsing, not about a minimum count. The narrow
        gold set is the person-written one with every field but severity dropped,
        so no gold answer here is one the test made up.
        """
        narrowed = audited / "gold" / "severity-only"
        narrowed.mkdir()
        for path in sorted((audited / "gold" / "incidents").glob("*.json")):
            gold = json.loads(path.read_text(encoding="utf-8"))
            gold["fields"] = {"severity": gold["fields"]["severity"]}
            (narrowed / path.name).write_text(json.dumps(gold, indent=2), encoding="utf-8")

        result = _eval(audited, monkeypatch, gold="gold/severity-only")

        assert result.exit_code == 0, result.output
        scored = {
            field: _percentage(line)
            for field, line in _field_lines(result.output).items()
            if _percentage(line)
        }
        assert scored == {"severity": "100.0%"}
