"""R6.25 — the schema a step is shown lets a declared `enum` field hold only one
of its values, or null.

The model was never shown `severity`'s vocabulary, and on 2026-09-29
`gpt-5.4-mini` answered it with `latency`, `ERROR` and a heap-usage sentence.
The declaration is the one place a field is defined (R6.10), so its values
reach the model in the schema, as its names already do.

Asserted on what a record able to name a field may hold, whatever nests it:
the property the rule states, not the shape that happens to give it.
"""

from __future__ import annotations

from dossier.domain.fields import OutputSchema, declare_fields, enum_values, json_schema
from dossier.domain.schemas import StageOutput

SEVERITY = {"kind": "enum", "values": ["minor", "major", "critical"]}
STATUS = {"kind": "enum", "values": ["open", "closed"]}
RESOLUTION_DATE = {"kind": "date"}
ROOT_CAUSE = {"kind": "free_text", "judge": "rubrics/root_cause.md"}
LOSS_AMOUNT = {"kind": "amount", "currency": "CHF"}


def _generated(**fields: dict) -> dict:
    declaration = {"fields": fields}
    return json_schema(declare_fields(declaration), values=enum_values(declaration))


def _resolved(schema: dict, node: object) -> object:
    if isinstance(node, dict) and "$ref" in node:
        return schema["$defs"][node["$ref"].removeprefix("#/$defs/")]
    return node


def _records(schema: dict) -> list[dict]:
    """Every record an answer's `fields` may hold."""
    items = _resolved(schema, schema["properties"]["fields"]["items"])
    return [_resolved(schema, variant) for variant in items.get("anyOf", [items])]


def _names(record: dict) -> list[str]:
    named = record["properties"]["field"]
    return [named["const"]] if "const" in named else list(named["enum"])


def _vocabulary(value: dict) -> list | None:
    """The values a `value` schema admits, in order, or `None` when it admits any."""
    if "enum" in value:
        return list(value["enum"])
    if value.get("type") == "null":
        return [None]
    if "anyOf" in value:
        branches = [_vocabulary(branch) for branch in value["anyOf"]]
        return None if any(branch is None for branch in branches) else sum(branches, [])
    return None


def _holding(schema: dict, field: str) -> list[list | None]:
    """What each record able to name `field` lets its value be."""
    return [
        _vocabulary(record["properties"]["value"])
        for record in _records(schema)
        if field in _names(record)
    ]


def _before(names: list[str]) -> dict:
    """The schema as it was generated before R6.25: `field` narrowed, nothing else."""
    schema = StageOutput.model_json_schema()
    schema["$defs"]["FieldRecord"]["properties"]["field"] = {"title": "Field", "enum": names}
    return schema


class TestAnEnumFieldsValuesAreInItsSchema:
    """R6.25 — an enum field's record holds one of its values, or null, and nothing else."""

    def test_severity_is_held_to_its_vocabulary(self):
        """Row 1 — the one where the model is told which words `severity` takes."""
        schema = _generated(
            severity=SEVERITY, resolution_date=RESOLUTION_DATE, root_cause=ROOT_CAUSE
        )

        assert _holding(schema, "severity") == [["minor", "major", "critical", None]]
        assert _holding(schema, "resolution_date") == [None]
        assert _holding(schema, "root_cause") == [None]

    def test_two_enums_keep_their_own_vocabularies(self):
        """Row 2 — the one where `severity` cannot hold `closed`, nor `status` `critical`."""
        schema = _generated(severity=SEVERITY, status=STATUS, root_cause=ROOT_CAUSE)

        assert _holding(schema, "severity") == [["minor", "major", "critical", None]]
        assert _holding(schema, "status") == [["open", "closed", None]]

    def test_every_declared_field_is_named_where_every_model_reads_it(self):
        """Row 3 — the one where the second variant's field is not lost.

        Found live on 2026-09-29: a model reading the schema as guidance answers
        the fields the first variant names, and `gpt-5.4-mini` left `severity`
        out of every page until the answer's `fields` named them all.
        """
        schema = _generated(
            severity=SEVERITY, resolution_date=RESOLUTION_DATE, root_cause=ROOT_CAUSE
        )

        assert schema["properties"]["fields"]["description"] == (
            "Answer every one of these fields: severity, resolution_date, root_cause."
        )

    def test_a_declaration_with_no_enum_is_shown_what_it_was_before(self):
        """Row 4, counter-example — the one where no key moves (R6.12)."""
        names = ["loss_amount", "resolution_date", "root_cause"]
        schema = _generated(
            loss_amount=LOSS_AMOUNT, resolution_date=RESOLUTION_DATE, root_cause=ROOT_CAUSE
        )

        assert schema == _before(names)
        hashed = OutputSchema(schema=schema, declaration_hash="6e0d4b27" * 8)
        assert (
            hashed.generated_schema_hash
            == OutputSchema(
                schema=_before(names), declaration_hash="6e0d4b27" * 8
            ).generated_schema_hash
        )
