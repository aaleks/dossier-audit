"""R21.3 — overlapping detections are masked as one span covering both, under the
longer one's type.

Presidio finds `example.ch` as a URL inside `erika.mustermann@example.ch`, and
a person inside a company's name. Masking each on its own would leave a piece
of the value between two placeholders, so overlapping spans become one, and
the span covers both: masking more is the safe side.
"""

from __future__ import annotations


def _detection(start: int, end: int, entity: str, score: float = 0.85):
    from dossier.domain.masking import Detection

    return Detection(start=start, end=end, entity=entity, score=score)


def _merged(detections):
    from dossier.domain.masking import merged

    return merged(detections)


class TestOverlappingDetectionsAreMaskedAsOne:
    """R21.3 — one span for what overlaps, typed by the longer detection."""

    def test_a_url_inside_an_email_address_is_part_of_the_address(self):
        """Row 1: the one where no fragment of the address is left between placeholders."""
        from dossier.domain.masking import masked

        text = "Write to erika.mustermann@example.ch today."
        address = text.index("erika")
        url = text.index("example.ch")
        detections = [
            _detection(address, address + 27, "EMAIL_ADDRESS", 1.0),
            _detection(url, url + 10, "URL", 0.5),
        ]

        assert _merged(detections) == [_detection(address, address + 27, "EMAIL_ADDRESS", 1.0)]
        assert masked(text, _merged(detections)) == "Write to [EMAIL_ADDRESS_1] today."

    def test_two_spans_that_overlap_become_one_covering_both(self):
        """Row 2: the one where a person and a company share a name.

        `Hans Muster AG`: PERSON over `Hans Muster` (0-11), ORGANIZATION over
        `Muster AG` (5-14). One span 0-14, the longer's type.
        """
        detections = [_detection(0, 11, "PERSON"), _detection(5, 14, "ORGANIZATION")]

        (span,) = _merged(detections)

        assert (span.start, span.end, span.entity) == (0, 14, "PERSON")

    def test_a_tie_in_length_is_broken_by_the_type_first_by_name(self):
        """Row 3: the one where nothing about the detections tells them apart."""
        detections = [_detection(0, 6, "PERSON"), _detection(0, 6, "LOCATION")]

        (span,) = _merged(detections)

        assert (span.start, span.end, span.entity) == (0, 6, "LOCATION")

    def test_detections_that_only_sit_near_each_other_stay_apart(self):
        """Row 4, a counter-example: the one where two names are a few words apart."""
        detections = [_detection(21, 32, "PERSON"), _detection(0, 16, "PERSON")]

        assert _merged(detections) == [
            _detection(0, 16, "PERSON"),
            _detection(21, 32, "PERSON"),
        ]
