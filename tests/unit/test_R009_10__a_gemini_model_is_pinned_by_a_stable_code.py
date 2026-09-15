"""R9.10 — a Gemini model is pinned by a stable model code, never by a `latest`,
preview or experimental name.

Google names a model three ways: a stable code, which it documents as not
changing; a `-latest` name, which it re-points at each release; and preview and
experimental names, which it may replace under the same name. Only the first is
a pin. Gemini reports no digest, so this pin -- like Anthropic's -- rests on the
provider's documentation, and nothing is checked before the first call.
"""

from __future__ import annotations

import pytest

from dossier.domain.model_id import check_pinned


class TestAGeminiModelIsPinnedByAStableCode:
    """R9.10 — a stable code pins a Gemini model; a moving name does not."""

    def test_a_stable_code_is_accepted(self):
        """Example 1: the one that is the project's default model."""
        check_pinned("gemini:gemini-3.5-flash-lite")

    def test_a_latest_name_is_refused_naming_it(self):
        """Example 2: the one Google re-points at each release."""
        with pytest.raises(ValueError) as error:
            check_pinned("gemini:gemini-flash-lite-latest")

        assert "gemini:gemini-flash-lite-latest" in str(error.value)

    def test_a_preview_name_is_refused(self):
        """Example 3: the one that can be replaced under the same name."""
        with pytest.raises(ValueError):
            check_pinned("gemini:gemini-3-flash-preview")

    def test_an_openai_snapshot_is_not_this_rules_to_judge(self):
        """Counter-example (row 4): the one where R9.9 pins it, not this rule."""
        check_pinned("openai:gpt-4o-2024-08-06")
