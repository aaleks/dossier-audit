"""R7.43 — a `list` field's item precision and recall are printed and recorded
beside its percentage, and gate nothing.

One verdict per document (R7.41) says a list was wrong, not whether the run
missed systems or invented them. Precision is, of the items the run named, how
many gold names; recall is, of gold's items, how many the run named; each summed
over the documents scored. The figures are the same in the terminal and in
MLflow, which is a second place to read a figure and never a second way of
arriving at one (spec 011).

The documents are `_fixtures.md`'s "A list field": 50.0%, precision 3 of 4,
recall 3 of 5.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeTracker, NoModelClient

from dossier.application.eval import record_eval
from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import (
    FieldDelta,
    FieldKind,
    FieldTotal,
    GoldField,
    ItemCounts,
    describe_items,
    per_field,
    score_document,
)

FIELD = "affected_systems"
GROUNDED = FieldCheck(FieldVerdict.VALID)
ABSTAINED = FieldCheck(FieldVerdict.ABSTAINED, "not stated in document")

# (document, what the run names, what gold holds): the list example.
LIST_EXAMPLE = (
    ("INC-4821", ["payments-api"], ["payments-api", "ledger-batch"]),
    ("INC-4822", ["ledger-batch"], ["ledger-batch"]),
    ("INC-4901", ["payments-api"], ["payments-api"]),
    ("INC-5455", ["payments-api"], ["upload-service"]),
)


def scored(document: str, named: list[str], gold: list[str] | None):
    records = [
        FieldRecord(field=FIELD, value=value, source=Evidence(document=document, span=value))
        for value in named
    ] or [FieldRecord(field=FIELD, value=None, reason="not stated in document")]
    return score_document(
        document=document,
        records=records,
        checks=[GROUNDED if named else ABSTAINED] * len(records),
        gold={FIELD: GoldField(value=gold)},
        kinds={FIELD: FieldKind.LIST},
    )


def total_of(example) -> FieldTotal:
    (total,) = per_field([scored(*row) for row in example], declared=[FIELD])
    return total


def recorded(total: FieldTotal) -> dict[str, float]:
    tracker = FakeTracker()
    record_eval(
        tracker,
        experiment="dossier-audit/incident-audit/eval",
        pipeline="incident-audit",
        run_id="20260806T142203Z-4f1a",
        model="anthropic:claude-sonnet-4-5-20250929",
        gold="gold/incidents",
        gold_files={"INC-4821.json": b'{"document": "INC-4821"}'},
        totals=(total,),
    )
    return tracker.runs[0].metrics


class TestAListReportsItemPrecisionAndRecall:
    """R7.43 — the items, beside the verdict, and never instead of it."""

    def test_the_list_example_reads_its_items_beside_its_percentage(self):
        """Row 1 — the one where the run misses systems more than it invents them."""
        total = total_of(LIST_EXAMPLE)

        assert total.percentage == 50.0
        assert total.items == ItemCounts(matched=3, named=4, expected=5)
        assert describe_items(total) == "items: precision 75.0% (3/4), recall 60.0% (3/5)"
        assert recorded(total) == {
            "accuracy/affected_systems": 50.0,
            "precision/affected_systems": 75.0,
            "recall/affected_systems": 60.0,
            "accuracy/overall": 50.0,
        }

    def test_an_item_named_where_gold_abstains_costs_precision_and_not_recall(self):
        """Row 2 — the one where the run names a system gold says the document does not."""
        names_one = total_of(
            (
                ("INC-4822", ["ledger-batch"], None),
                ("INC-4901", ["payments-api"], ["payments-api"]),
            )
        )
        abstains = total_of(
            (
                ("INC-4822", [], None),
                ("INC-4901", ["payments-api"], ["payments-api"]),
            )
        )

        assert names_one.items == ItemCounts(matched=1, named=2, expected=1)
        assert names_one.items.precision < abstains.items.precision
        assert names_one.items.recall == abstains.items.recall

    def test_a_lower_precision_at_the_same_percentage_is_not_a_regression(self):
        """Row 3, counter-example — the one the change gate does not look at (R7.8)."""
        before = FieldTotal(FIELD, correct=2, scored=4, items=ItemCounts(3, 4, 5))
        after = FieldTotal(FIELD, correct=2, scored=4, items=ItemCounts(2, 4, 5))

        assert not FieldDelta(FIELD, before=before, after=after).regressed

    def test_a_share_that_does_not_divide_evenly_is_rounded(self):
        """Row 5 — the one where 2 of 3 are named right and 2 of 3 are found."""
        total = total_of(
            [
                (
                    "INC-4821",
                    ["payments-api", "ledger-batch", "checkout"],
                    ["payments-api", "checkout", "settlement"],
                )
            ]
        )

        assert describe_items(total) == "items: precision 66.7% (2/3), recall 66.7% (2/3)"
        metrics = recorded(total)
        assert metrics["precision/affected_systems"] == pytest.approx(200 / 3)
        assert metrics["recall/affected_systems"] == pytest.approx(200 / 3)

    def test_a_run_that_named_nothing_has_no_precision_rather_than_zero(self):
        """Row 4, counter-example — the one where nothing named means nothing wrong."""
        total = total_of((document, [], gold) for document, _, gold in LIST_EXAMPLE)

        assert total.items.precision is None
        assert describe_items(total) == "items: precision --, recall 0.0% (0/5)"
        metrics = recorded(total)
        assert "precision/affected_systems" not in metrics
        assert metrics["recall/affected_systems"] == 0.0

    def test_the_command_records_the_figures_it_printed(self, workspace: Path, monkeypatch):
        """Row 1, through `dossier eval` with tracking on: the line and the record agree.

        R7.45's workspace: the list example beside an `enum` field. The rows above
        record through `record_eval`; the command records through `finish_eval`,
        and only this row watches the figures leave the command.
        """
        from tests.acceptance.test_R007_45__eval_scores_a_list_field import (
            GOLD_SYSTEMS,
            PIPELINE,
            _audited,
            _cli,
            _line_of,
        )

        import dossier.cli.bootstrap as cli

        _audited(workspace, monkeypatch, GOLD_SYSTEMS)
        tracker = FakeTracker()
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        assert result.exit_code == 0, result.output
        line = " ".join(_line_of(result.output, FIELD).split())
        assert line.startswith(
            "affected_systems 50.0% items: precision 75.0% (3/4), recall 60.0% (3/5)"
        ), result.output
        (run,) = tracker.runs
        assert {name: run.metrics[name] for name in run.metrics if FIELD in name} == {
            "accuracy/affected_systems": 50.0,
            "precision/affected_systems": 75.0,
            "recall/affected_systems": 60.0,
        }
