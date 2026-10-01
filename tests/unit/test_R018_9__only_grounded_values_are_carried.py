"""R18.9 — a filter field is carried only when the run grounded it, and a text
field is embedded in the document's record chunk.

A value whose span is not in the document is scored incorrect whatever it says
(R7.4). Carried, it would let a filter return a category the document does not
support. The verdicts are the ones `eval` would reach, from the same check
(R6.4), so the index and the score agree about what is evidenced.
"""

from __future__ import annotations

from dossier.domain.grounding import FieldVerdict
from dossier.domain.index import IndexFields, carried
from dossier.domain.schemas import FieldRecord

FIELDS = IndexFields(
    filter=("failure_category", "component", "root_cause_category"),
    embed=("root_cause",),
)
ROOT_CAUSE = (
    "Certificate renewal and certificate deployment were two separate processes, "
    "and only the first was automated."
)
VALID = FieldVerdict.VALID


def record(field: str, value) -> FieldRecord:
    return FieldRecord(field=field, value=value)


class TestOnlyGroundedValuesAreCarried:
    """R18.9 — grounded categories to filter on, grounded text to embed."""

    def test_a_grounded_category_is_a_value_to_filter_on(self):
        """Row 1 — the one where `INC-4830`'s `failure_category` is grounded."""
        kept = carried(FIELDS, [(record("failure_category", "certificate-expiry"), VALID)])

        assert kept.values == {"failure_category": "certificate-expiry"}
        assert kept.record_text is None

    def test_grounded_free_text_is_the_record_chunks_text(self):
        """Row 2 — the one whose `root_cause` is grounded."""
        kept = carried(FIELDS, [(record("root_cause", ROOT_CAUSE), VALID)])

        assert kept.record_text == f"root_cause: {ROOT_CAUSE}"
        assert kept.values == {}

    def test_an_ungrounded_value_is_left_out_and_counted(self):
        """Row 3, counter-example — the one naming `payments-api`, absent from `INC-4830`."""
        kept = carried(
            FIELDS,
            [
                (record("failure_category", "certificate-expiry"), VALID),
                (record("component", "payments-api"), FieldVerdict.UNGROUNDED),
            ],
        )

        assert kept.values == {"failure_category": "certificate-expiry"}
        assert kept.left_out == {"ungrounded": 1}
        assert kept.note("INC-4830") == "INC-4830: 1 value left out: ungrounded"

    def test_an_abstention_is_no_value_and_not_left_out(self):
        """Row 4, counter-example — the one where `root_cause_category` was abstained."""
        abstained = FieldRecord(field="root_cause_category", reason="not stated in document")

        kept = carried(FIELDS, [(abstained, FieldVerdict.ABSTAINED)])

        assert kept.values == {}
        assert kept.left_out == {}
        assert kept.note("INC-4830") is None

    def test_an_enum_is_carried_in_its_declared_spelling(self):
        """Row 5 — the one answered `Certificate-Expiry` where `certificate-expiry` is declared.

        The check let it through folded (R6.26), as eval scores it. Carried as
        answered, a filter on the declared value would miss it.
        """
        kept = carried(
            FIELDS,
            [(record("failure_category", "Certificate-Expiry"), VALID)],
            enums={"failure_category": ("certificate-expiry", "capacity-exhaustion")},
        )

        assert kept.values == {"failure_category": "certificate-expiry"}
