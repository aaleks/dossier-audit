"""R5.12 — `dossier run` says how many tokens each step spent, and a document
served from cache spent none.

The wording, without a run: `step_line` is the one function both the terminal
and the record's description compose a step's line with (R11.17), so what it
says about tokens is said once. `tokens=None` is a step that asked no model.
"""

from __future__ import annotations

from dossier.domain.tracking import step_line
from dossier.domain.usage import Tokens


def line(tokens: Tokens | None, **counts: int) -> str:
    base = {"step": "extract", "documents": 3, "cached": 0, "failed": 0}
    return step_line(**{**base, **counts}, tokens=tokens)


class TestTheStepLineSaysWhatWasSpent:
    """R5.12 — the step line's token clause."""

    def test_a_step_that_asked_says_what_it_spent(self):
        """Row 1: the one where three documents cost 3,612 in and 636 out."""
        assert line(Tokens(input=3612, output=636)) == (
            "extract: 3 document(s) · 0 from cache · 0 failed · 3,612 tokens in · 636 out"
        )

    def test_a_step_that_asked_nothing_says_nothing_about_tokens(self):
        """Row 2: the one served entirely from cache: no clause at all."""
        assert line(None, cached=3) == "extract: 3 document(s) · 3 from cache · 0 failed"

    def test_a_count_the_provider_did_not_give_is_not_reported_as_zero(self):
        """Row 5, a counter-example: the one where a side is `None`."""
        assert line(Tokens(input=None, output=636)).endswith("· 0 failed · tokens not reported")

    def test_the_separator_is_a_comma_whatever_the_locale(self):
        """Row 1's boundary: a million is `1,000,000` on every machine (R0.4)."""
        assert line(Tokens(input=1_000_000, output=0)).endswith("· 1,000,000 tokens in · 0 out")

    def test_the_tokens_come_last(self):
        """Row 4: the one with a failure and findings: what was spent ends the line."""
        assert line(Tokens(input=4816, output=848), failed=1, findings=2) == (
            "extract: 3 document(s) · 0 from cache · 1 failed · 2 finding(s)"
            " · 4,816 tokens in · 848 out"
        )
