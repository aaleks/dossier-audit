"""R10.10 — a record's name is rendered from the name template for its command.

The acceptance test beside this one proves a command *gives* its record that
name. This one proves what renders, which is a pure decision over values the
caller already holds: no environment, no clock, no server.

The values are `_fixtures.md`'s -- the run id used in provenance examples, and
the pinned model identifier -- so a row in spec 010 and an assertion here name
the same thing.
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import (
    _PLACEHOLDER,
    DEFAULT_NAMES,
    NAME_PLACEHOLDERS,
    SEPARATOR,
    run_name,
)

RUN_ID = "20260806T142203Z-4f1a"
SECOND_RUN_ID = "20260907T090000Z-bbbb"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
# The `gold/incidents` set hash of `_fixtures.md`, padded to the 64 characters a
# real one carries: the eight are the display convention, never the value.
GOLD_HASH = "3b7e1d90" + "0" * 56


class TestANameIsRenderedFromItsTemplate:
    """R10.10 — a record's name is rendered from the name template for its command."""

    def test_an_eval_is_named_for_the_run_it_scored_and_the_model_that_produced_it(self):
        """Example 1: the one where nothing is configured and the default renders.

        Both values are ones the command already holds. Neither is abbreviated:
        a shortened model identifier is a second spelling of the one value whose
        whole point is to be exact (R0.6).
        """
        assert (
            run_name(kind="eval", values={"run_id": RUN_ID, "model": MODEL}, environ={})
            == f"eval {RUN_ID} · {MODEL}"
        )

    def test_a_configured_prefix_opens_the_name_with_its_own_separator(self):
        """Example 2: the one where a person wants every record of theirs prefixed.

        The separator belongs to `{prefix}`, not to the template around it. One
        variable then prefixes every kind without six templates being rewritten,
        and an unset prefix leaves no stray ` · ` for anything to strip.
        """
        assert (
            run_name(
                kind="eval",
                values={"run_id": RUN_ID, "model": MODEL},
                environ={"DOSSIER_MLFLOW_RUN_PREFIX": "nightly"},
            )
            == f"nightly · eval {RUN_ID} · {MODEL}"
        )

    def test_a_per_kind_template_wins_over_the_default(self):
        """Example 3: the one where a person writes their own comparison name.

        `DOSSIER_MLFLOW_RUN_NAME_<KIND>` is the per-command variable, as
        `DOSSIER_MLFLOW_EXPERIMENT_<KIND>` is (R10.2). A template with no
        `{prefix}` takes none: what renders is what was written.
        """
        assert (
            run_name(
                kind="compare",
                values={"a": RUN_ID, "b": SECOND_RUN_ID},
                environ={
                    "DOSSIER_MLFLOW_RUN_NAME_COMPARE": "{a} vs {b}",
                    "DOSSIER_MLFLOW_RUN_PREFIX": "nightly",
                },
            )
            == f"{RUN_ID} vs {SECOND_RUN_ID}"
        )

    def test_a_hash_in_a_name_is_its_eight_character_display_form(self):
        """Example 5: the one where a person names their evals by the answers.

        The caller hands over the hash it holds, which is the whole 64 (R0.7);
        what a name shows is the eight every spec displays. Truncating at the
        call site instead would put the decision in six places, and a name that
        carried all 64 would push everything a person came to read off the row.
        """
        assert (
            run_name(
                kind="eval",
                values={"run_id": RUN_ID, "model": MODEL, "gold_hash": GOLD_HASH},
                environ={"DOSSIER_MLFLOW_RUN_NAME_EVAL": "{prefix}eval {gold_hash}"},
            )
            == "eval 3b7e1d90"
        )

    def test_a_template_naming_a_placeholder_the_command_cannot_fill_is_refused(self):
        """Example 4: the one where a run's template asks for a gold set.

        Refused rather than rendered literally, and refused rather than left
        blank: a run named `{gold} 20260806T142203Z-4f1a` is a name nobody meant,
        and records pile up under it unnoticed. The message names the variable it
        came from, because that is the thing to go and edit (R10.2's shape).
        """
        with pytest.raises(ValueError) as refused:
            run_name(
                kind="run",
                values={"run_id": RUN_ID},
                environ={"DOSSIER_MLFLOW_RUN_NAME_RUN": "{gold} {run_id}"},
            )

        assert "DOSSIER_MLFLOW_RUN_NAME_RUN" in str(refused.value)
        assert "{gold}" in str(refused.value)
        assert "{run_id}" in str(refused.value), "the message lists what a run may use"

    def test_a_run_with_nothing_configured_is_named_exactly_its_run_id(self):
        """Counter-example (row 6): the one where nobody configured anything.

        Byte-identical to R11.1 row 1. Every name recorded before this rule is
        unchanged until someone sets a variable, which is the whole of why
        `{prefix}` renders empty rather than rendering a separator.
        """
        name = run_name(kind="run", values={"run_id": RUN_ID}, environ={})

        assert name == RUN_ID
        assert SEPARATOR not in name

    @pytest.mark.parametrize("kind", sorted(DEFAULT_NAMES))
    def test_every_kind_has_a_default_it_can_actually_render(self, kind: str):
        """The boundary the table itself sits on.

        A default naming a placeholder its own kind cannot fill would refuse that
        command on a machine that configured nothing -- the one path nobody would
        think to test, because it is the path that was working yesterday.
        """
        assert set(_PLACEHOLDER.findall(DEFAULT_NAMES[kind])) <= set(NAME_PLACEHOLDERS[kind])
