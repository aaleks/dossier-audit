"""R6.10 — a step's fields are declared once, in YAML, and everything else is generated.

The domain half: turning a parsed declaration into fields and kinds. Reading the
YAML is `config/`'s job, so every case here hands the decision a plain mapping --
which is also why none of them needs a file.
"""

from __future__ import annotations

import pytest

from dossier.domain.fields import declare_fields, json_schema
from dossier.domain.schemas import StageOutput
from dossier.domain.scoring import FieldKind

KINDS = ("amount", "date", "enum", "reference", "free_text")

# Spec 006's declaration, parsed: five fields, one of each kind.
INCIDENT = {
    "fields": {
        "loss_amount": {"kind": "amount", "currency": "CHF"},
        "resolution_date": {"kind": "date"},
        "severity": {"kind": "enum", "values": ["minor", "major", "critical"]},
        "affected_systems": {"kind": "reference"},
        "root_cause": {"kind": "free_text", "judge": "rubrics/root_cause.md"},
    }
}


def _record_properties(schema: object) -> dict | None:
    """The properties of a field record, wherever a schema nests it."""
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and "field" in properties:
            return properties
        for value in schema.values():
            found = _record_properties(value)
            if found is not None:
                return found
    return None


def _field_names(schema: object) -> list[str] | None:
    """The names a generated schema allows in a field record's `field`."""
    return _record_properties(schema)["field"].get("enum")


class TestFieldsAreDeclaredOnce:
    """R6.10 — the declaration is the only place a field's name and kind are written."""

    def test_a_field_added_to_the_declaration_appears_in_the_generated_schema(self):
        """Example 1: the one where adding `affected_systems` needs no other edit.

        The schema shown to the model is a function of the declaration alone, so
        a field declared once is a field the model is asked for.
        """
        without = {
            "fields": {
                name: spec
                for name, spec in INCIDENT["fields"].items()
                if name != "affected_systems"
            }
        }

        before = json_schema(declare_fields(without))
        after = json_schema(declare_fields(INCIDENT))

        assert "affected_systems" not in _field_names(before)
        assert _field_names(after) == list(INCIDENT["fields"])

    def test_the_scorer_field_list_is_exactly_the_declaration(self):
        """Example 2: the one where neither side has an entry the other lacks.

        Compared as the mapping `score_document` takes, so the scorer consumes
        what the declaration produced and never a list written anywhere else.
        """
        kinds = declare_fields(INCIDENT)

        assert kinds == {
            "loss_amount": FieldKind.AMOUNT,
            "resolution_date": FieldKind.DATE,
            "severity": FieldKind.ENUM,
            "affected_systems": FieldKind.REFERENCE,
            "root_cause": FieldKind.FREE_TEXT,
        }

    def test_the_schema_shown_to_the_model_is_derived_not_written_by_hand(self):
        """Example 3: the one where there is no committed JSON Schema to drift.

        Every property the answer is validated against appears, unchanged, in
        the schema the model is shown -- except `field`, narrowed to the declared
        names. A hand-written copy is a second definition, and the first property
        added to the record model would be one the model was never asked for.
        """
        generated = _record_properties(json_schema(declare_fields(INCIDENT)))
        validated = _record_properties(StageOutput.model_json_schema())

        assert set(generated) == set(validated)
        for name, spec in validated.items():
            if name != "field":
                assert generated[name] == spec, name
        assert generated["field"]["enum"] == list(INCIDENT["fields"])

    def test_an_enum_with_no_values_is_refused_naming_the_field(self):
        """Example 4: the one where `severity` is an enum with no vocabulary.

        An enum with no `values` can match nothing, so every answer to it would
        score incorrect -- confidently, and months later. Refused at load time
        instead, naming the field and what it is missing.
        """
        with pytest.raises(ValueError) as error:
            declare_fields({"fields": {"severity": {"kind": "enum"}}})

        message = str(error.value)
        assert "severity" in message
        assert "values" in message

    def test_free_text_with_no_judge_is_refused_naming_the_field(self):
        """Example 5: the one where `root_cause` names no rubric to be judged by.

        Free text is scored by a judge against a written rubric (spec 007,
        "Scorers"), and there is no default rubric to fall back on. Without one
        the field could only be string-compared -- the defect this prevents.
        """
        with pytest.raises(ValueError) as error:
            declare_fields({"fields": {"root_cause": {"kind": "free_text"}}})

        message = str(error.value)
        assert "root_cause" in message
        assert "judge" in message

    def test_changing_a_kind_is_configuration_not_a_second_definition(self):
        """Counter-example (row 6): the one where `loss_amount` is judged instead of compared.

        Moving a field from `amount` to `free_text` is an edit to the one
        declaration. The scorer's choice follows it, and nothing else names the
        field's kind to disagree -- that is what `kind` is.
        """
        judged = {
            "fields": {
                **INCIDENT["fields"],
                "loss_amount": {"kind": "free_text", "judge": "rubrics/loss_amount.md"},
            }
        }

        before = declare_fields(INCIDENT)
        after = declare_fields(judged)

        assert after["loss_amount"] is FieldKind.FREE_TEXT
        assert {name: kind for name, kind in after.items() if name != "loss_amount"} == {
            name: kind for name, kind in before.items() if name != "loss_amount"
        }

    def test_an_unknown_kind_names_the_field_and_the_kinds_that_exist(self):
        """The one where `loss_amount` declares a kind nobody can score (R3.10 row 4).

        The kind is what picks the scorer, so a kind outside the five is a field
        nobody decided how to score. Listing the five turns the error into its
        own fix.
        """
        with pytest.raises(ValueError) as error:
            declare_fields({"fields": {"loss_amount": {"kind": "money", "currency": "CHF"}}})

        message = str(error.value)
        assert "loss_amount" in message
        assert "money" in message
        for kind in KINDS:
            assert kind in message
