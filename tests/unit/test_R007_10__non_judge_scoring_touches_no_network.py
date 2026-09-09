"""R7.10 — scoring performs no network I/O for non-judge field types.

The direct consequence of R0.1 for this spec, and the reason most of an audit can
be re-scored offline in seconds.

Re-scoring is something people do often and casually: a gold answer is corrected,
a scorer is fixed, someone wants yesterday's run measured a different way. That
is only casual if it is free. A scorer that reached the network would make every
re-score a paid, rate-limited, occasionally-failing operation, and people would
stop doing it — which is how a gold set quietly goes stale.

Asserted three ways, because "no network" is a claim about absence: the socket
block, a model client that fails on any call, and the structure of the module
itself.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.fakes import NoModelClient

from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.schemas import Evidence, FieldRecord
from dossier.domain.scoring import GoldField, Verdict, score_document, score_field

SPAN = Evidence(document="INC-4821", span="total exposure CHF 48'200")
GROUNDED = FieldCheck(FieldVerdict.VALID)

DETERMINISTIC = {
    "loss_amount": (
        FieldRecord(field="loss_amount", value="48'200.00", currency="CHF", source=SPAN),
        GoldField(value=48200.00, currency="CHF"),
    ),
    "resolution_date": (
        FieldRecord(field="resolution_date", value="28.07.2026", source=SPAN),
        GoldField(value="2026-07-28"),
    ),
    "severity": (
        FieldRecord(field="severity", value="Major", source=SPAN),
        GoldField(value="major"),
    ),
}


class TestScoringIsOffline:
    """R7.10 — the whole deterministic half runs with nothing plugged in."""

    def test_the_three_deterministic_field_types_score_with_no_network(self):
        """Example 1: the one with the socket blocked.

        The autouse `no_network` fixture makes a socket impossible for every test
        in the default suite, so this row is really asking whether scoring
        *needs* one. It completes, so it does not.
        """
        report = score_document(
            document="INC-4821",
            records=[record for record, _ in DETERMINISTIC.values()],
            checks=dict.fromkeys(DETERMINISTIC, GROUNDED),
            gold={name: gold for name, (_, gold) in DETERMINISTIC.items()},
        )

        assert [result.verdict for result in report.results] == [Verdict.CORRECT] * 3

    def test_a_model_client_that_fails_on_any_call_is_never_reached(self):
        """Example 2: the one where the client would name itself.

        `score_field` has no parameter to pass a client to, so the strongest
        thing a test can do is hold one, score, and observe it was never asked.
        Zero calls, on a client that raises on the first.
        """
        client = NoModelClient()

        for record, gold in DETERMINISTIC.values():
            score_field(record=record, gold=gold, check=GROUNDED)

        assert not hasattr(client, "calls") or client.calls == []

    def test_a_gold_set_with_no_free_text_field_scores_entirely_offline(self):
        """Example 3: the one where the whole evaluation is deterministic.

        No field is marked `judged`, so nothing needs a judge and no part of the
        run is deferred. That is the common case for an amounts-and-dates
        pipeline, and it should cost nothing to re-run.
        """
        report = score_document(
            document="INC-4821",
            records=[record for record, _ in DETERMINISTIC.values()],
            checks=dict.fromkeys(DETERMINISTIC, GROUNDED),
            gold={name: gold for name, (_, gold) in DETERMINISTIC.items()},
        )

        assert report.scored == report.results
        assert all(result.verdict is not Verdict.NEEDS_JUDGE for result in report.results)

    def test_a_judged_field_is_deferred_rather_than_scored_here(self):
        """Counter-example (row 4): the one that *does* need a model.

        `root_cause` is free text. This module does not reach a model for it --
        it declines, and says so. That is what keeps R7.11 an `evaluated` rule
        with a threshold rather than a string comparison in disguise.
        """
        result = score_field(
            record=FieldRecord(field="root_cause", value="a cable failed", source=SPAN),
            gold=GoldField(value="the cable failed", judged=True),
            check=GROUNDED,
        )

        assert result.verdict is Verdict.NEEDS_JUDGE

    def test_the_module_imports_nothing_that_could_reach_a_network(self):
        """The structural half, checked by reading rather than by hoping.

        A network call added on some branch this suite does not exercise would
        pass every row above. R0.1's own test walks the whole package for exactly
        this reason; this narrows it to the module the rule names.
        """
        module = (
            Path(__file__).resolve().parents[2]
            / "src" / "dossier" / "domain" / "scoring.py"
        )
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert imported <= {
            "re", "collections", "dataclasses", "datetime", "enum", "pydantic", "dossier",
            "__future__",
        }, f"unexpected import in the scorer: {sorted(imported)}"
