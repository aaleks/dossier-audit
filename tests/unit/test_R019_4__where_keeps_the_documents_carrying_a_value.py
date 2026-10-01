"""R19.4 — `--where FIELD=VALUE` keeps only the documents carrying that value,
and a field or value the index does not carry is refused.

The value is read as the declaration spells it, so a filter finds what `embed`
carried (R18.9 row 5). The filtering itself is the index's, proved live in
`tests/integration/test_R019_4__postgres_search_filters.py`; what the command
line may ask for is decided here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance import test_R019_8__search_lists_what_answers_the_query as searched
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX

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
        """Row 9, counter-example — the one that names no value at all."""
        with pytest.raises(UnfilterableWhere) as refused:
            _wheres("checkout")

        assert str(refused.value) == "--where takes FIELD=VALUE; got checkout"

    def test_a_where_with_an_empty_side_is_refused(self):
        """Row 9, counter-example — a field and no value, and a value and no field.

        Each side alone would otherwise be read as something it is not: an empty
        value of a declared field, or a field named nothing.
        """
        for given in ("component=", "=checkout", "failure_category= "):
            with pytest.raises(UnfilterableWhere) as refused:
                _wheres(given)

            assert str(refused.value) == f"--where takes FIELD=VALUE; got {given}"

    def test_no_where_filters_nothing(self):
        """Row 8, counter-example — the one with no `--where`."""
        assert _wheres() == {}


# R19.8's workspace, synced, run and embedded, the index a fake; its fixtures
# shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


def _search(workspace: Path, monkeypatch, *more: str):
    return _cli(workspace, monkeypatch, "search", INDEX, searched.QUERY, *more)


class TestWhereThroughTheCommand:
    """R19.4 — what `--where` asks of the index, and what it refuses unasked."""

    def test_the_index_is_asked_for_the_declared_spelling(
        self, embedded: Path, monkeypatch, index
    ):
        """Rows 1 and 2 — the one filtered on the failure, typed in capitals."""
        result = _search(
            embedded, monkeypatch, "--where", "failure_category=CERTIFICATE-EXPIRY"
        )

        assert result.exit_code == 0, result.output
        assert index.searches[-1]["where"] == {"failure_category": ("certificate-expiry",)}
        assert result.stdout.splitlines()[1].startswith("1. INC-4830"), result.output

    def test_an_unknown_field_or_value_is_refused_before_the_model_is_asked(
        self, embedded: Path, monkeypatch, embedder, index
    ):
        """Rows 5 and 6 — the one on free text, and the one on a value never declared."""
        before = embedder.calls
        for given, said in (
            ("root_cause=certificate", "root_cause is not a filter of incidents"),
            (
                "failure_category=meteor-strike",
                "meteor-strike is not a value of failure_category",
            ),
        ):
            result = _search(embedded, monkeypatch, "--where", given)

            assert result.exit_code == 2, result.output
            assert said in result.stderr, result.stderr
        assert embedder.calls == before
        assert index.searches == []
