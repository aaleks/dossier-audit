"""R10.10 — a record's name is rendered from the name template for its command.

The acceptance test beside this one proves a command *gives* its record that
name. This one proves what renders, which is a pure decision over values the
caller already holds: no environment, no clock, no server.

The values are `_fixtures.md`'s -- the run id used in provenance examples, and
the pinned model identifier -- so a row in spec 010 and an assertion here name
the same thing.
"""

from __future__ import annotations

from dossier.domain.tracking import run_name

RUN_ID = "20260806T142203Z-4f1a"
MODEL = "anthropic:claude-sonnet-4-5-20250929"


class TestANameIsRenderedFromItsTemplate:
    """R10.10 — a record's name is rendered from the name template for its command."""

    def test_an_eval_is_named_for_the_run_it_scored_and_the_model_that_produced_it(self):
        """Example 1: the one where nothing is configured and the default renders.

        Both values are ones the command already holds. Neither is abbreviated:
        a shortened model identifier is a second spelling of the one value whose
        whole point is to be exact (R0.6).
        """
        assert (
            run_name(kind="eval", values={"run_id": RUN_ID, "model": MODEL})
            == f"eval {RUN_ID} · {MODEL}"
        )
