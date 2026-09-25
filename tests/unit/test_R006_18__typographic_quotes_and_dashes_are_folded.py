"""R6.18 — typographic quotes, apostrophes and dashes compare equal to their plain forms.

`’ ‘ ‛ ′` are `'`; `“ ” „ ‟ ″` are `"`; `‐ ‑ ‒ – — ―` and the minus sign `−` are
`-`. A typesetter writes `CHF 48’200` and a model quoting it types
`CHF 48'200`; both sides are folded, so either may carry either form.
"""

from __future__ import annotations

import pytest

from dossier.domain.grounding import locate_span


class TestTypographicQuotesAndDashesAreFolded:
    """R6.18 — a quote mark is a quote mark, and a dash is a dash."""

    def test_a_typographic_apostrophe_is_an_apostrophe(self):
        """Row 1: the one where `INC-4821`'s figure was typeset."""
        text = "total exposure CHF 48’200"

        assert locate_span("total exposure CHF 48'200", document_text=text)

    def test_typographic_double_quotes_are_straight_ones(self):
        """Row 2: the one where the text says “supported”."""
        text = "the claim was “supported”"

        assert locate_span('the claim was "supported"', document_text=text)

    @pytest.mark.parametrize(
        "mark",
        ["‘", "’", "‛", "′"],
        ids=["left single", "right single", "reversed", "prime"],
    )
    def test_every_single_quote_form_is_an_apostrophe(self, mark: str):
        """Row 1, for each form the rule names."""
        assert locate_span("CHF 48'200", document_text=f"CHF 48{mark}200")

    @pytest.mark.parametrize(
        "mark",
        ["“", "”", "„", "‟", "″"],
        ids=["left double", "right double", "low double", "reversed double", "double prime"],
    )
    def test_every_double_quote_form_is_a_straight_one(self, mark: str):
        """Row 2, for each form the rule names."""
        assert locate_span('"supported"', document_text=f"{mark}supported{mark}")

    @pytest.mark.parametrize(
        "dash",
        ["‐", "‑", "‒", "–", "—", "―", "−"],
        ids=["hyphen", "non-breaking", "figure", "en", "em", "bar", "minus"],
    )
    def test_every_dash_is_a_hyphen_minus(self, dash: str):
        """Row 3: the one where the time range was typeset with an en dash."""
        assert locate_span("declined 09:12-09:54", document_text=f"declined 09:12{dash}09:54")

    def test_a_comma_is_not_an_apostrophe(self):
        """Counter-example, row 4: R6.4 row 3 still holds."""
        text = "total exposure CHF 48'200"

        assert not locate_span("total exposure CHF 48,200", document_text=text)
