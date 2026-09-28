"""R7.39 — `dossier eval` scores a `boolean` and a `duration` field per field,
beside the others.

What a person running the contract audit sees (`docs/second-use-case.md`,
finding 2): `auto_renew` and `notice_period` listed with their own percentages
(R7.2), and a miss named with the reason R7.38 gave it (R7.25). The contracts
and their answers are `_fixtures.md`'s "Fields on the contracts".

Each contract is one document here, keyed by the contract, so the test is about
the two kinds and not about grouping (R3.15 has its own).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import IssueTracker, RoutedModel, found

PIPELINE = "contract-renewal"
SOURCE_ID = "contracts-signed"
SOURCE_TYPE = "contract-register"
FIELDS = ("auto_renew", "notice_period")

DECLARATION = """\
fields:
  auto_renew:    {kind: boolean}
  notice_period: {kind: duration}
"""

CONTRACTS = {
    "ACME-2024": (
        "# ACME-2024\n\n"
        "This Agreement renews automatically for successive one-year terms.\n"
        "Either party may terminate on ninety (90) days' written notice.\n"
    ),
    "GLOBEX-2023": (
        "# GLOBEX-2023\n\n"
        "This Agreement shall not renew automatically.\n"
        "Either party may terminate on three (3) months' written notice.\n"
    ),
}

GOLD = {
    "ACME-2024": {"auto_renew": {"value": True}, "notice_period": {"value": "90 days"}},
    "GLOBEX-2023": {"auto_renew": {"value": False}, "notice_period": {"value": "3 months"}},
}

# The run: `auto_renew` right for both, `notice_period` `90 days` for both --
# right for ACME-2024, and wrong for GLOBEX-2023, whose span says three months.
RENEWS = "renews automatically for successive one-year terms"
DOES_NOT_RENEW = "This Agreement shall not renew automatically"

ANSWERS = {
    "ACME-2024": [
        found("ACME-2024", "auto_renew", True, RENEWS),
        found("ACME-2024", "notice_period", "90 days", "on ninety (90) days' written notice"),
    ],
    "GLOBEX-2023": [
        found("GLOBEX-2023", "auto_renew", False, DOES_NOT_RENEW),
        found("GLOBEX-2023", "notice_period", "90 days", "three (3) months' written notice"),
    ],
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


def _workspace(workspace: Path, monkeypatch, declaration: str = DECLARATION) -> RoutedModel:
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=[SOURCE_ID],
        outputs={"extract": "schemas/contract.yaml"},
        write_declaration=False,
    )
    (workspace / "pipelines" / PIPELINE / "schemas" / "contract.yaml").write_text(
        declaration, encoding="utf-8"
    )
    gold = workspace / "gold" / "contracts"
    gold.mkdir(parents=True)
    for document, fields in GOLD.items():
        (gold / f"{document}.json").write_text(
            json.dumps(
                {
                    "document": document,
                    "verified_by": "a.aleks",
                    "verified_at": "2026-09-28",
                    "fields": fields,
                }
            ),
            encoding="utf-8",
        )
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(CONTRACTS)
    )
    model = RoutedModel(ANSWERS)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> tuple[Path, RoutedModel]:
    """The two contracts, synced and run, with their gold set in place."""
    model = _workspace(workspace, monkeypatch)
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return workspace, model


class TestEvalScoresABooleanAndADuration:
    """R7.39 — `dossier eval` scores a `boolean` and a `duration` field per field."""

    def test_each_field_is_listed_with_its_own_percentage(self, audited, monkeypatch):
        """Row 1 — the one where auto_renew is right twice and notice_period once."""
        workspace, model = audited

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/contracts")

        assert result.exit_code == 0, result.output
        assert "100.0%" in _line_of(result.output, "auto_renew"), result.output
        assert "50.0%" in _line_of(result.output, "notice_period"), result.output
        # One call per contract, both from `run`: scoring asks no model (R7.10).
        assert model.call_count == 2

    def test_the_miss_is_named_with_why_a_month_is_not_days(self, audited, monkeypatch):
        """Row 2 — the one where 90 days is not three months, and the report says why."""
        workspace, _ = audited

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/contracts")

        under = " ".join(_lines_under(result.output, "notice_period"))
        assert "GLOBEX-2023" in under, result.output
        assert "90 days" in under and "3 months" in under, under
        assert "month is not a fixed number of days" in under, under
        assert _lines_under(result.output, "auto_renew") == []

    def test_a_number_kind_is_refused_naming_the_kinds_there_are(
        self, workspace: Path, monkeypatch
    ):
        """Row 3, counter-example — the one where a count is an amount, not a `number`.

        Refused where the pipeline is first loaded, which is `sync`: before a
        document is fetched, let alone a model asked.
        """
        model = _workspace(
            workspace, monkeypatch, declaration="fields:\n  notice_days: {kind: number}\n"
        )

        result = _cli(workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "notice_days" in result.output
        assert "boolean" in result.output and "duration" in result.output, result.output
        assert model.call_count == 0
