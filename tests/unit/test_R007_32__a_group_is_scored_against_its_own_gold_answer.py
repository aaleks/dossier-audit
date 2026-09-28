"""R7.32 — a `per_group` step's answers are scored per group, against the gold
answer whose `document` is the group.

The question was asked of the contract, so the answer is verified for the
contract: `gold/contracts/ACME-2024.json` says `"document": "ACME-2024"`, and
gold is matched by that field rather than by the file's name. Which member a
value was cited from does not decide whether it is right -- that is grounding's
question (R7.4) -- and a value grounded in amendment 3 that matches the verified
date is correct.

Through the CLI, `run` then `eval`, because the eval reproduces the run from its
manifest (R4.15) and prints the line a person reads. The model is a fake that
answers each contract's call with the values in its members (R0.1).
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline

PIPELINE = "contract-renewal"
GOLD = "gold/contracts"
DECLARATION = """\
fields:
  renewal_date:  {kind: date}
  liability_cap: {kind: amount, currency: EUR}
"""
CONTRACTS = {
    "ACME-2024/amendment-3.md": "# Amendment 3\n\nThe term is extended to 2027-03-31.\n",
    "ACME-2024/master.md": "# ACME master agreement\n\nLiability is capped at EUR 2,000,000.\n",
    "GLOBEX-2023/master.md": "# GLOBEX master agreement\n\nThe term ends 2026-12-31.\n",
}
ANSWERS = {
    "ACME-2024": [
        {
            "field": "renewal_date",
            "value": "2027-03-31",
            "source": {"document": "ACME-2024/amendment-3.md", "span": "2027-03-31"},
        },
        {
            "field": "liability_cap",
            "value": 2000000.0,
            "currency": "EUR",
            "source": {"document": "ACME-2024/master.md", "span": "EUR 2,000,000"},
        },
    ],
    "GLOBEX-2023": [
        {
            "field": "renewal_date",
            "value": "2026-12-31",
            "source": {"document": "GLOBEX-2023/master.md", "span": "2026-12-31"},
        },
        {"field": "liability_cap", "value": None, "reason": "not stated in document"},
    ],
}


class Contracts:
    """Answers each contract's call with that contract's scripted fields."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        group = next(name for name in ANSWERS if f'<document key="{name}/' in prompt)
        return json.dumps({"document": group, "fields": ANSWERS[group]})


def _gold(document: str, fields: dict) -> str:
    return json.dumps(
        {
            "document": document,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-27",
            "fields": fields,
        }
    )


ACME_GOLD = {
    "renewal_date": {"value": "2027-03-31"},
    "liability_cap": {"value": 2000000.0, "currency": "EUR"},
}
GLOBEX_GOLD = {
    "renewal_date": {"value": "2026-12-31"},
    "liability_cap": {"value": None, "reason": "not stated in document"},
}


def _eval(workspace: Path, monkeypatch, gold: dict[str, str]):
    """Sync, run and eval a `per_group` step over two contracts, against `gold`."""
    import dossier.cli.bootstrap as cli

    for key, text in CONTRACTS.items():
        path = workspace / "inbox" / "contracts" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: contracts\n    type: folder\n    path: inbox/contracts/\n",
        encoding="utf-8",
    )
    path = write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["contracts"],
        modes={"extract": "per_group"},
        outputs={"extract": "schemas/contract.yaml"},
    )
    (path.parent / "schemas" / "contract.yaml").write_text(DECLARATION, encoding="utf-8")
    directory = workspace / GOLD
    directory.mkdir(parents=True)
    for name, content in gold.items():
        (directory / name).write_text(content, encoding="utf-8")

    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Contracts())
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


class TestAGroupIsScoredAgainstItsOwnGoldAnswer:
    """R7.32 — a contract's answer against the contract's verified answer."""

    def test_a_value_cited_from_an_amendment_is_scored_for_the_contract(
        self, workspace: Path, monkeypatch
    ):
        """Rows 1 and 2: the one where two contracts are two scored units.

        `renewal_date` is cited from amendment 3 and `liability_cap` from the
        master; both are scored against `ACME-2024`'s gold, and both are right.
        The first line counts what was scored: two contracts, not the three
        files the run read.
        """
        result = _eval(
            workspace,
            monkeypatch,
            {
                "ACME-2024.json": _gold("ACME-2024", ACME_GOLD),
                "GLOBEX-2023.json": _gold("GLOBEX-2023", GLOBEX_GOLD),
            },
        )

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == "2 groups · 2 fields · overall 100.0%", result.output
        assert "  renewal_date       100.0%" in lines, result.output

    def test_a_gold_answer_for_a_member_is_not_scored(self, workspace: Path, monkeypatch):
        """Row 3, a counter-example: the one verified for a file, not the contract.

        The run answered for `GLOBEX-2023`, and no answer is filed under
        `GLOBEX-2023/master.md`. So that gold file scores nothing, and one
        contract is scored, not two.
        """
        result = _eval(
            workspace,
            monkeypatch,
            {
                "ACME-2024.json": _gold("ACME-2024", ACME_GOLD),
                "GLOBEX-2023-master.json": _gold("GLOBEX-2023/master.md", GLOBEX_GOLD),
            },
        )

        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[0] == "1 group · 2 fields · overall 100.0%"
