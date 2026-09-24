"""R6.17 — a span is compared with its document after Unicode compatibility folding.

NFKC, on both sides: `ﬁ` is `fi`, a full-width `Ｃ` is `C`, and an `é` written as
`e` plus a combining accent is the `é` a keyboard types. A PDF text layer spells
`certiﬁcate` with a ligature, a model quoting it types `certificate`, and before
this the honest citation came back `ungrounded`.
"""

from __future__ import annotations

from dossier.domain.grounding import locate_span, page_of_span

LIGATURE = "ﬁ"  # ﬁ
COMBINING_ACUTE = "́"


class TestUnicodeCompatibilityFormsAreFolded:
    """R6.17 — what a reader cannot tell apart, the search does not either."""

    def test_a_ligature_in_the_text_is_found_by_the_letters(self):
        """Row 1: the one where `INC-4830`'s text layer has `ﬁ`."""
        text = f"the renewed certi{LIGATURE}cate was never deployed"

        assert locate_span("the renewed certificate", document_text=text)

    def test_a_ligature_in_the_span_is_found_in_the_letters(self):
        """Row 2: both sides are folded, so either may carry the ligature."""
        text = "the renewed certificate was never deployed"

        assert locate_span(f"the renewed certi{LIGATURE}cate", document_text=text)

    def test_a_decomposed_accent_is_the_accent_a_keyboard_types(self):
        """Row 3: `e` plus U+0301 in the text, `é` in the span."""
        text = f"Cafe{COMBINING_ACUTE} au lait, 09:12"

        assert locate_span("Café au lait", document_text=text)

    def test_a_full_width_letter_is_its_ascii_form(self):
        """Row 1's reason at another codepoint: `ＣＨＦ` is `CHF`."""
        assert locate_span("CHF 48'200", document_text="total exposure ＣＨＦ 48'200")

    def test_the_page_follows_the_same_fold(self):
        """A span that grounds has the page it grounds on (R6.14): one search, not two."""
        text = f"<!-- page 1 -->\nintro\n<!-- page 2 -->\nthe renewed certi{LIGATURE}cate"

        assert page_of_span("the renewed certificate", document_text=text) == 2

    def test_case_is_not_folded(self):
        """Counter-example, row 4: the one where `MAJOR` is not `major`."""
        assert not locate_span("MAJOR", document_text="severity: major")
