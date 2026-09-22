"""R14.9 — which rubrics a judge's record looks up, and under which names.

The decision, in the layer that owns it: given the rubric hash of every judged
field and the fields R7.15 withheld, which (name, hash) pairs does the record go
looking for. Pure, so the acceptance test only has to show the lookup reaching
an eval and a calibration.
"""

from __future__ import annotations

ROOT_CAUSE = "f7a2d9c4" * 8
CONTRIBUTING = "0e52dd18" * 8


class TestAJudgeLooksUpTheRubricOfEveryFieldItMayReport:
    """R14.9 — a judge's record links the rubric of every field it did not withhold."""

    def test_every_judged_field_is_looked_up_by_its_rubric_hash(self):
        """Row 1: the one where each field asks for the version carrying its own words.

        In field order, so two evals of one pipeline ask the registry the same
        questions in the same order (R0.4).
        """
        from dossier.domain.prompts import rubric_links

        assert rubric_links(
            "incident-audit",
            {"root_cause": ROOT_CAUSE, "contributing_factors": CONTRIBUTING},
        ) == [
            ("incident-audit.judge.contributing_factors", CONTRIBUTING),
            ("incident-audit.judge.root_cause", ROOT_CAUSE),
        ]

    def test_a_withheld_field_is_not_looked_up(self):
        """Counter-example (row 5): the one whose rubric no reported figure came from."""
        from dossier.domain.prompts import rubric_links

        assert rubric_links(
            "incident-audit",
            {"root_cause": ROOT_CAUSE, "contributing_factors": CONTRIBUTING},
            withheld={"root_cause"},
        ) == [("incident-audit.judge.contributing_factors", CONTRIBUTING)]

    def test_a_prefix_is_in_every_name_looked_up(self):
        """Row 4: the one where the lookup is under the name a publish would send (R14.8)."""
        from dossier.domain.prompts import rubric_links

        assert rubric_links("incident-audit", {"root_cause": ROOT_CAUSE}, prefix="sandbox") == [
            ("sandbox.incident-audit.judge.root_cause", ROOT_CAUSE)
        ]
