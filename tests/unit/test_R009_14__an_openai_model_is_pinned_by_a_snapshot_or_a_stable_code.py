"""R9.14 — an OpenAI model is pinned by a dated snapshot or a stable code.

A stage key holds the identifier, not the weights (R5.3 row 4), so an identifier
naming something OpenAI re-points would let one key mean a different model from
one month to the next (R0.5). Two forms do not move: a snapshot ending in its
release date, written `-YYYY-MM-DD` -- not Anthropic's `-YYYYMMDD` (R0.6) -- and
a stable code with no snapshot behind it.

This replaces R9.9, which accepted only the first and so refused a correctly
pinned `openai:gpt-5.4-mini`. What R9.9 got right is kept here: `gpt-4o` is still
refused, and by name, because nothing in its shape says it moves.
"""

from __future__ import annotations

import pytest

from dossier.domain.model_id import check_pinned


class TestAnOpenAIModelIsPinnedByASnapshotOrAStableCode:
    """R9.14 — a snapshot or a stable code pins an OpenAI model; a moving name does not."""

    def test_a_stable_code_is_accepted(self):
        """Example 1: the one OpenAI publishes with no snapshot behind it.

        The case R9.9 got wrong. `gpt-5.4-mini` is not a dated snapshot and is
        not an alias for one; refusing it refuses a model that is pinned.
        """
        check_pinned("openai:gpt-5.4-mini")

    def test_a_dated_snapshot_is_accepted(self):
        """Example 2: the one where `gpt-4o` is pinned to its 2024-08-06 snapshot."""
        check_pinned("openai:gpt-4o-2024-08-06")

    def test_an_alias_is_refused_naming_it(self):
        """Example 3: the one where `gpt-4o` alone could be another snapshot next month.

        OpenAI re-points the alias at each release, and nothing in the key would
        say so. Nothing in the *name* says so either, which is why this one is
        refused from a list rather than by shape.
        """
        with pytest.raises(ValueError) as error:
            check_pinned("openai:gpt-4o")

        assert "openai:gpt-4o" in str(error.value)

    def test_a_latest_name_is_refused(self):
        """Example 4: the one whose name says outright that it moves."""
        with pytest.raises(ValueError):
            check_pinned("openai:chatgpt-4o-latest")

    def test_an_anthropic_id_is_not_this_rules_to_judge(self):
        """Counter-example (row 5): the one where R0.6 pins it, not this rule.

        Anthropic writes its date without dashes. Holding it to OpenAI's form
        would refuse a correctly pinned model -- which is the mistake R9.9 made
        one provider over.
        """
        check_pinned("anthropic:claude-sonnet-4-5-20250929")
