"""R21.22 — a value is masked with its document's numbering, and a value the
document does not hold takes the next number of its type.

A gold value or a calibration candidate is written by a person against the
original document, so it names the client as the document does. Masked on its
own it would start again at `[PERSON_1]`, and a judge or a scorer would compare
`[PERSON_2]` in the run's answer with `[PERSON_1]` in the gold value. So it is
masked with the document's mapping: the document's values take the document's
placeholders, and anything else the masker finds continues the count.

`PLAY-6001` names `Hans Muster` first and `Erika Mustermann` second
(`_fixtures.md`), so they are `[PERSON_1]` and `[PERSON_2]` in its masked view.
"""

from __future__ import annotations

MAPPING = {
    "[PERSON_1]": "Hans Muster",
    "[PERSON_2]": "Erika Mustermann",
    "[IBAN_CODE_1]": "CH93 0076 2011 6238 5295 7",
}


def _like(text: str, detections=()) -> str:
    from dossier.domain.masking import Masking, MaskingDeclaration, mask_like

    declaration = MaskingDeclaration(
        masker="presidio",
        languages=["en"],
        score_threshold=0.5,
        entities=["PERSON", "IBAN_CODE"],
    )
    masking = Masking(declaration=declaration, declaration_hash="0" * 64)
    return mask_like(text, list(detections), masking, MAPPING)


def _person(text: str, value: str):
    from dossier.domain.masking import Detection

    start = text.index(value)
    return Detection(start=start, end=start + len(value), entity="PERSON", score=0.85)


class TestAValueIsMaskedWithItsDocumentsNumbering:
    """R21.22 — the document's placeholders for its values; the next number for the rest."""

    def test_a_value_of_the_document_takes_the_documents_placeholder(self):
        """Row 1: the one where the candidate names the document's second person."""
        assert (
            _like("Erika Mustermann's settlement was held")
            == "[PERSON_2]'s settlement was held"
        )

    def test_a_value_is_matched_as_two_mentions_of_it_are(self):
        """Row 2: the one where the candidate writes the name in capitals."""
        assert _like("ERIKA  MUSTERMANN confirmed") == "[PERSON_2] confirmed"

    def test_a_value_the_document_does_not_hold_takes_the_next_number(self):
        """Row 3: the one where the masker finds a person the document never names."""
        text = "Max Muster confirmed it to Hans Muster."

        assert _like(text, [_person(text, "Max Muster")]) == (
            "[PERSON_3] confirmed it to [PERSON_1]."
        )

    def test_a_text_with_no_value_and_nothing_detected_is_left_as_written(self):
        """Row 4, a counter-example: the one where the candidate names no client."""
        assert _like("the settlement export never ran") == "the settlement export never ran"
