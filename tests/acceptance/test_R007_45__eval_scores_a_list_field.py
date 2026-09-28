"""R7.45 — `dossier eval` scores a `list` field per field, beside the others.

What a person auditing incidents sees once `affected_systems` is declared a
list: its own percentage (R7.2), its items' precision and recall beside it
(R7.43), and each miss named with what was missing and what was not in gold
(R7.25). The incidents, gold and answers are `_fixtures.md`'s "A list field":
the scoring example's four documents, answered one record per system (R6.24).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, IssueTracker, RoutedModel, found

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
FIELDS = ("severity", "affected_systems")

DECLARATION = """\
fields:
  severity:         {kind: enum, values: [minor, major, critical]}
  affected_systems: {kind: list}
"""

SEVERITY = {
    "INC-4821": "major",
    "INC-4822": "minor",
    "INC-4901": "critical",
    "INC-5455": "major",
}

GOLD_SYSTEMS = {
    "INC-4821": ["payments-api", "ledger-batch"],
    "INC-4822": ["ledger-batch"],
    "INC-4901": ["payments-api"],
    "INC-5455": ["upload-service"],
}

# One record per system, each citing the system's own name. `INC-4821` misses
# `ledger-batch`; `INC-5455` names the system its document says was ruled out,
# which is grounded, so the miss is about the value and not the evidence (R7.4).
SYSTEMS = {
    "INC-4821": [("payments-api", "payments-api")],
    "INC-4822": [("ledger-batch", "ledger-batch")],
    "INC-4901": [("payments-api", "payments-api")],
    "INC-5455": [("payments-api", "payments-api was checked and ruled out")],
}

ANSWERS = {
    document: [
        found(document, "severity", SEVERITY[document], f"assessed as {SEVERITY[document]}"),
        *(
            found(document, "affected_systems", value, span)
            for value, span in SYSTEMS[document]
        ),
    ]
    for document in ISSUES
}


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _line_of(output: str, field: str) -> str:
    return next((line for line in output.splitlines() if line.split()[:1] == [field]), "")


def _lines_under(output: str, field: str) -> list[str]:
    """The indented lines following `field`'s own line, up to the next field."""
    lines = output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.split()[:1] == [field]]
    if not starts:
        return []
    collected = []
    for line in lines[starts[0] + 1 :]:
        if line.split()[:1] and line.split()[0] in FIELDS:
            break
        collected.append(line)
    return [line for line in collected if line.strip()]


def _write_gold(workspace: Path, systems: dict[str, object]) -> None:
    gold = workspace / "gold" / "incidents"
    gold.mkdir(parents=True, exist_ok=True)
    for document, value in systems.items():
        (gold / f"{document}.json").write_text(
            json.dumps(
                {
                    "document": document,
                    "verified_by": "a.aleks",
                    "verified_at": "2026-09-28",
                    "fields": {
                        "severity": {"value": SEVERITY[document]},
                        "affected_systems": {"value": value},
                    },
                }
            ),
            encoding="utf-8",
        )


def _audited(workspace: Path, monkeypatch, gold: dict[str, object]) -> RoutedModel:
    """The four incidents, synced and run, with `gold` in place."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=[SOURCE_ID],
        outputs={"extract": "schemas/incident.yaml"},
        write_declaration=False,
    )
    (workspace / "pipelines" / PIPELINE / "schemas" / "incident.yaml").write_text(
        DECLARATION, encoding="utf-8"
    )
    _write_gold(workspace, gold)
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    model = RoutedModel(ANSWERS)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return model


class TestEvalScoresAListField:
    """R7.45 — `dossier eval` scores a `list` field per field, beside the others."""

    def test_the_list_has_its_own_percentage_and_its_items_beside_it(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one where half the lists are right and the items say which way."""
        model = _audited(workspace, monkeypatch, GOLD_SYSTEMS)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        assert result.exit_code == 0, result.output
        assert "100.0%" in _line_of(result.output, "severity"), result.output
        line = _line_of(result.output, "affected_systems")
        assert "50.0%" in line, result.output
        assert "precision 75.0% (3/4)" in line, line
        assert "recall 60.0% (3/5)" in line, line
        # One call per incident, all from `run`: scoring asks no model (R7.10).
        assert model.call_count == 4

    def test_each_miss_names_what_was_missing_and_what_was_not_in_gold(
        self, workspace: Path, monkeypatch
    ):
        """Row 2 — the one where a missed system and an invented one read differently."""
        _audited(workspace, monkeypatch, GOLD_SYSTEMS)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        under = _lines_under(result.output, "affected_systems")
        missed = next((line for line in under if "INC-4821" in line), "")
        invented = next((line for line in under if "INC-5455" in line), "")
        assert "missing: ledger-batch" in missed, result.output
        assert "missing: upload-service" in invented, result.output
        assert "not in gold: payments-api" in invented, result.output
        assert not any(document in " ".join(under) for document in ("INC-4822", "INC-4901"))
        assert _lines_under(result.output, "severity") == []

    def test_a_list_written_as_one_string_in_gold_is_refused(
        self, workspace: Path, monkeypatch
    ):
        """Row 3, counter-example — the one where gold wrote the list as a comma string.

        Splitting it on the comma would be a guess, since an item may hold one,
        so the gold answer is refused before anything is scored (R7.44).
        """
        _audited(
            workspace, monkeypatch, {**GOLD_SYSTEMS, "INC-4821": "payments-api, ledger-batch"}
        )

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        assert result.exit_code == 2, result.output
        assert "INC-4821" in result.output and "affected_systems" in result.output
        assert "%" not in result.output, result.output
