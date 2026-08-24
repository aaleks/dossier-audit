"""R6.6 — a field may not be both non-null and missing a source.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest
from tests.grounding_fixtures import LOSS_SPAN, SEVERITY_SPAN, STAGE_INPUTS

from dossier.domain.grounding import FieldVerdict, check_field
from dossier.domain.schemas import Evidence, FieldRecord


class TestNonNullNeedsASource:
    """R6.6 — a figure without evidence is what this system exists not to produce."""

    def test_a_value_with_no_source_is_invalid(self):
        """Example 1: the one where the model answered and cited nothing."""
        check = check_field(
            FieldRecord(field="severity", value="major"), input_documents=STAGE_INPUTS
        )

        assert check.verdict is FieldVerdict.INVALID

    def test_a_value_with_an_empty_span_is_invalid(self):
        """Example 2: the one where the citation is present and useless.

        An empty span can never be located, so it can never be checked. Accepting
        it would be a citation that is structurally present and semantically
        absent — worse than none, because it survives a shallow look.
        """
        check = check_field(
            FieldRecord(
                field="severity",
                value="major",
                source=Evidence(document="INC-4821", span=""),
            ),
            input_documents=STAGE_INPUTS,
        )

        assert check.is_failure

    def test_zero_is_a_value_not_an_absence(self):
        """Example 3: the one where a falsy value must not be read as missing.

        `loss_amount: 0.00` is a finding — an incident with no financial impact.
        Treating it as absent would silently turn a real answer into an
        abstention, and the audit would report that nobody knew.
        """
        check = check_field(
            FieldRecord(
                field="loss_amount",
                value=0.00,
                currency="CHF",
                source=Evidence(document="INC-4821", span=LOSS_SPAN),
            ),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.VALID

    @pytest.mark.parametrize(
        "value", [pytest.param(False, id="false"), pytest.param("", id="empty-string")]
    )
    def test_other_falsy_values_are_also_values(self, value: object):
        """The same boundary from two more directions.

        `auto_renew: false` and an empty string are answers. Any check written as
        `if not record.value` would turn all three of these into abstentions, and
        that is the single easiest mistake to make in this function.
        """
        check = check_field(
            FieldRecord(
                field="auto_renew",
                value=value,
                source=Evidence(document="INC-4821", span=SEVERITY_SPAN),
            ),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.VALID

    def test_null_with_a_reason_needs_no_source(self):
        """Counter-example (row 4): the one where R6.5 takes precedence."""
        check = check_field(
            FieldRecord(field="root_cause", value=None, reason="not stated"),
            input_documents=STAGE_INPUTS,
        )

        assert check.verdict is FieldVerdict.ABSTAINED
