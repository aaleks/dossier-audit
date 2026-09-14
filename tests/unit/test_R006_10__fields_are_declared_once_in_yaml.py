"""R6.10 — a step's fields are declared once, in YAML, and everything else is generated.

The domain half: turning a parsed declaration into fields and kinds. Reading the
YAML is `config/`'s job, so every case here hands the decision a plain mapping --
which is also why none of them needs a file.
"""

from __future__ import annotations

import pytest

from dossier.domain.fields import declare_fields
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


class TestFieldsAreDeclaredOnce:
    """R6.10 — the declaration is the only place a field's name and kind are written."""

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
