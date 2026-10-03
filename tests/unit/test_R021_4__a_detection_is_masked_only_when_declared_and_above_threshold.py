"""R21.4 — a detection is masked only when its type is declared, its score reaches
the declared threshold, and its text is not allow-listed.

Presidio scores a detection with a constant per recogniser: a name 0.85, an
IBAN 1.0, a phone number 0.4 alone and 0.75 beside a word such as `phone`. So
the threshold decides which recognisers count, and it is the pipeline
author's: `cid.yaml` declares it, and `dossier` ships no number.
"""

from __future__ import annotations

ENTITIES = ("PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "ORGANIZATION")


def _kept(text: str, value: str, entity: str, score: float, *, allow=()) -> bool:
    """Whether the one detection of `value` in `text` survives."""
    from dossier.domain.masking import Detection, kept

    start = text.index(value)
    detection = Detection(start=start, end=start + len(value), entity=entity, score=score)
    survivors = kept(text, [detection], entities=ENTITIES, threshold=0.5, allow=allow)
    assert survivors in ([], [detection])
    return survivors == [detection]


class TestADetectionIsMaskedOnlyWhenDeclaredAndAboveThreshold:
    """R21.4 — declared, at or above the threshold, and not allow-listed."""

    def test_a_name_well_above_the_threshold_is_masked(self):
        """Row 1: the one where a person is found as people are."""
        assert _kept("Erika Mustermann called.", "Erika Mustermann", "PERSON", 0.85)

    def test_a_score_exactly_at_the_threshold_is_masked(self):
        """Row 2: the one where reaching the threshold is enough. The off-by-one row."""
        assert _kept("Ruf +41 44 555 01 23 an.", "+41 44 555 01 23", "PHONE_NUMBER", 0.5)

    def test_a_score_under_the_threshold_is_kept_as_written(self):
        """Row 3: the one where a phone number has no context word beside it."""
        assert not _kept("Ruf +41 44 555 01 23 an.", "+41 44 555 01 23", "PHONE_NUMBER", 0.4)

    def test_a_type_the_declaration_does_not_name_is_kept_as_written(self):
        """Row 4: the one where a site is found and nobody asked for sites."""
        assert not _kept("The Zurich site failed over.", "Zurich", "LOCATION", 0.85)

    def test_an_allow_listed_value_is_never_masked(self):
        """Row 5, a counter-example: the one where a vendor is allow-listed.

        `ORGANIZATION` is declared and `Oracle` scores 0.85; `allow.txt` names
        it, and an allow-listed value is never masked, whatever its score.
        """
        assert not _kept(
            "The Oracle database stalled.", "Oracle", "ORGANIZATION", 0.85, allow=["Oracle"]
        )
