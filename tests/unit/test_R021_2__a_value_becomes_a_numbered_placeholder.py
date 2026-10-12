"""R21.2 — a masked value becomes `[TYPE_n]`, numbered by first appearance in its
document, and the same value always gets the same number.

A pure decision over text and the spans a masker detected, so it is proved
here with plain values and no masker at all. The canaries are `_fixtures.md`'s
("Client identifying data").
"""

from __future__ import annotations

import pytest


def _person(text: str, value: str, *, at: int = 0):
    from dossier.domain.masking import Detection

    start = text.index(value, at)
    return Detection(start=start, end=start + len(value), entity="PERSON", score=0.85)


def _masked(text: str, detections) -> str:
    from dossier.domain.masking import masked

    return masked(text, detections)


class TestAValueBecomesANumberedPlaceholder:
    """R21.2 — numbered by first appearance, per type, per document."""

    def test_two_people_and_a_return_are_numbered_by_first_appearance(self):
        """Row 1: the one where the first person named comes back."""
        text = "Erika Mustermann called. Hans Muster confirmed. Erika Mustermann agreed."
        detections = [
            _person(text, "Erika Mustermann"),
            _person(text, "Hans Muster"),
            _person(text, "Erika Mustermann", at=20),
        ]

        assert (
            _masked(text, detections)
            == "[PERSON_1] called. [PERSON_2] confirmed. [PERSON_1] agreed."
        )

    def test_the_same_name_in_capitals_and_with_two_spaces_is_the_same_value(self):
        """Row 2: the one where a heading shouts the name.

        Compared after case folding and collapsing whitespace: a heading in
        capitals is not a second client.
        """
        text = "# ERIKA  MUSTERMANN\n\nErika Mustermann called."
        detections = [_person(text, "ERIKA  MUSTERMANN"), _person(text, "Erika Mustermann")]

        assert _masked(text, detections) == "# [PERSON_1]\n\n[PERSON_1] called."

    def test_each_type_is_numbered_on_its_own(self):
        """Row 3: the one where a person and an IBAN are both first of their kind."""
        from dossier.domain.masking import Detection

        text = "Erika Mustermann holds CH93 0076 2011 6238 5295 7."
        iban = text.index("CH93")
        detections = [
            _person(text, "Erika Mustermann"),
            Detection(start=iban, end=iban + 26, entity="IBAN_CODE", score=1.0),
        ]

        assert _masked(text, detections) == "[PERSON_1] holds [IBAN_CODE_1]."

    def test_a_surname_alone_is_a_different_value(self):
        """Row 4: the one where no surname is guessed at."""
        text = "Erika Mustermann called. Mustermann agreed."
        detections = [_person(text, "Erika Mustermann"), _person(text, "Mustermann", at=20)]

        assert _masked(text, detections) == "[PERSON_1] called. [PERSON_2] agreed."

    def test_numbering_starts_again_in_the_next_document(self):
        """Row 5, a counter-example: the one where each document counts from one.

        `PLAY-6001` names `Hans Muster` first and `PLAY-6002` names `Erika
        Mustermann` first: both are `[PERSON_1]` in their own document.
        """
        first = "Hans Muster reported it."
        second = "Erika Mustermann reported it."

        assert _masked(first, [_person(first, "Hans Muster")]) == "[PERSON_1] reported it."
        assert (
            _masked(second, [_person(second, "Erika Mustermann")]) == "[PERSON_1] reported it."
        )

    @pytest.mark.parametrize("possessive", ["'s", "’s", "'"])
    def test_a_possessive_is_not_part_of_the_value(self, possessive: str):
        """Row 6: the one where the masker's span takes in the `'s`, as Presidio's does.

        Measured live on 2026-10-12: `Erika Mustermann's` was numbered a second
        person, and the `'s` went with it.
        """
        text = f"Erika Mustermann called. Erika Mustermann{possessive} settlement was held."
        detections = [
            _person(text, "Erika Mustermann"),
            _person(text, f"Erika Mustermann{possessive}", at=20),
        ]

        assert _masked(text, detections) == (
            f"[PERSON_1] called. [PERSON_1]{possessive} settlement was held."
        )

    def test_an_apostrophe_inside_a_name_is_not_a_possessive(self):
        """Row 7, a counter-example: the one whose name holds an apostrophe."""
        text = "Siobhan O'Brien called."

        assert _masked(text, [_person(text, "Siobhan O'Brien")]) == "[PERSON_1] called."
