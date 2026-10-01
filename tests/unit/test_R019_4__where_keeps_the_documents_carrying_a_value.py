"""R19.4 — `--where FIELD=VALUE` keeps only the documents carrying that value,
and a field or value the index does not carry is refused.

The value is read as the declaration spells it, so a filter finds what `embed`
carried (R18.9 row 5). The filtering itself is the index's, proved live in
`tests/integration/test_R019_4__postgres_search_filters.py`; what the command
line may ask for is decided here.
"""

from __future__ import annotations

import pytest

from dossier.domain.search import UnfilterableWhere, wheres

FILTERS = (
    "failure_category",
    "component",
    "root_cause_category",
    "contributing_factor_category",
    "architecture_category",
)
ENUMS = {
    "failure_category": ("certificate-expiry", "capacity-exhaustion"),
    "component": ("checkout", "payments-api"),
}


def _wheres(*given: str):
    return wheres(given, index="incidents", filters=FILTERS, enums=ENUMS)


class TestWhereKeepsTheDocumentsCarryingAValue:
    """R19.4 — what `--where` may name, and how it is read."""

    def test_one_field_one_value(self):
        """Row 1 — the one filtered on the failure."""
        assert _wheres("failure_category=certificate-expiry") == {
            "failure_category": ("certificate-expiry",)
        }

    def test_a_value_is_read_in_the_declared_spelling(self):
        """Row 2 — the one typed in capitals."""
        assert _wheres("component=CHECKOUT") == {"component": ("checkout",)}

    def test_two_fields_must_both_hold(self):
        """Row 3 — the one filtered on the failure and the component."""
        assert _wheres("failure_category=certificate-expiry", "component=checkout") == {
            "failure_category": ("certificate-expiry",),
            "component": ("checkout",),
        }

    def test_one_field_given_twice_is_one_choice_of_values(self):
        """Row 4 — the one where either component will do."""
        assert _wheres("component=checkout", "component=payments-api") == {
            "component": ("checkout", "payments-api")
        }

    def test_a_field_the_index_does_not_filter_on_is_refused(self):
        """Row 5 — the one filtered on free text."""
        with pytest.raises(UnfilterableWhere) as refused:
            _wheres("root_cause=certificate")

        assert str(refused.value) == (
            "root_cause is not a filter of incidents; its filters are "
            "architecture_category, component, contributing_factor_category, "
            "failure_category, root_cause_category"
        )

    def test_a_value_the_field_does_not_declare_is_refused(self):
        """Row 6 — the one naming a failure no declaration lists."""
        with pytest.raises(UnfilterableWhere) as refused:
            _wheres("failure_category=meteor-strike")

        assert str(refused.value) == (
            "meteor-strike is not a value of failure_category; it declares "
            "capacity-exhaustion, certificate-expiry"
        )

    def test_a_where_without_an_equals_sign_is_refused(self):
        """The one that names no value at all."""
        with pytest.raises(UnfilterableWhere) as refused:
            _wheres("checkout")

        assert str(refused.value) == "--where takes FIELD=VALUE; got checkout"

    def test_no_where_filters_nothing(self):
        """Row 8, counter-example — the one with no `--where`."""
        assert _wheres() == {}
