"""R9.9 — an OpenAI model is pinned only by a dated snapshot.

`gpt-4o` is an alias OpenAI moves to each new snapshot, and a stage key holds the
identifier, not the weights (R5.3 row 4). An identifier naming the alias would
let one key mean a different model from one month to the next (R0.5). The
snapshot ends in its release date, written `-YYYY-MM-DD` -- not Anthropic's
`-YYYYMMDD` (R0.6).
"""

from __future__ import annotations

import pytest

from dossier.domain.model_id import check_pinned


class TestAnOpenAIModelIsPinnedByADatedSnapshot:
    """R9.9 — a dated snapshot pins an OpenAI model; an alias does not."""

    def test_a_dated_snapshot_is_accepted(self):
        """Example 1: the one where `gpt-4o` is pinned to its 2024-08-06 snapshot."""
        check_pinned("openai:gpt-4o-2024-08-06")

    def test_an_alias_is_refused_naming_it(self):
        """Example 2: the one where `gpt-4o` alone could be another snapshot next month.

        OpenAI re-points the alias at each release, and nothing in the key would
        say so.
        """
        with pytest.raises(ValueError) as error:
            check_pinned("openai:gpt-4o")

        assert "openai:gpt-4o" in str(error.value)

    def test_a_latest_name_is_refused(self):
        """Example 3: the one whose name says outright that it moves."""
        with pytest.raises(ValueError):
            check_pinned("openai:chatgpt-4o-latest")

    def test_an_anthropic_id_is_not_this_rules_to_judge(self):
        """Counter-example (row 4): the one where R0.6 pins it, not this rule.

        Anthropic writes its date without dashes. Holding it to OpenAI's form
        would refuse a correctly pinned model.
        """
        check_pinned("anthropic:claude-sonnet-4-5-20250929")
