"""R7.44 — gold for a `list` field is a non-empty array of strings, and only a
`list` field holds one.

A gold answer in the wrong shape is a definition of correct nobody can meet, so
it is refused when `dossier eval` reads the gold set, before anything is
scored. The one worth watching is row 3: a list written as one comma string is
what a gold set kept while the field was a `reference` looks like, and splitting
it on the comma would be a guess -- an item may hold one.

Values are `_fixtures.md`'s "A list field".
"""

from __future__ import annotations

from dossier.domain.scoring import FieldKind, GoldField, gold_shape_errors

KINDS = {"severity": FieldKind.ENUM, "affected_systems": FieldKind.LIST}


def errors(**answers) -> tuple[str, ...]:
    return gold_shape_errors(
        "INC-4821", {field: GoldField(**answer) for field, answer in answers.items()}, KINDS
    )


class TestAListInGoldIsAnArray:
    """R7.44 — an array for a list, and for nothing else."""

    def test_an_array_of_systems_is_a_list(self):
        """Row 1 — the one written as gold should be."""
        assert errors(affected_systems={"value": ["payments-api", "ledger-batch"]}) == ()

    def test_null_with_a_reason_is_a_verified_abstention(self):
        """Row 2 — the one where the document names no system (R7.3)."""
        assert (
            errors(affected_systems={"value": None, "reason": "not stated in document"}) == ()
        )

    def test_a_list_written_as_one_string_is_refused(self):
        """Row 3, counter-example — the one kept from when the field was a reference."""
        (error,) = errors(affected_systems={"value": "payments-api, ledger-batch"})

        assert "INC-4821" in error and "affected_systems" in error
        assert "array" in error

    def test_an_empty_array_is_refused_in_favour_of_null(self):
        """Row 4, counter-example — the one a run could never tell apart from silence."""
        (error,) = errors(affected_systems={"value": []})

        assert "INC-4821" in error and "affected_systems" in error
        assert "null" in error

    def test_an_array_for_an_enum_is_refused(self):
        """Row 5, counter-example — the one where only a list holds an array."""
        (error,) = errors(severity={"value": ["major"]})

        assert "INC-4821" in error and "severity" in error
        assert "list" in error
