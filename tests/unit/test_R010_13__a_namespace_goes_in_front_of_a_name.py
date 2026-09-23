"""R10.13 — the naming decision: a namespace in front of a name, or nothing.

One function for every name dossier publishes into MLflow's global namespace, so
a prompt and a dataset cannot be namespaced two different ways. Pure, so it is
proved here in milliseconds; the acceptance test beside it shows the namespace
reaching a publish, an eval and a run.
"""

from __future__ import annotations

import pytest


class TestANamespaceGoesInFrontOfAName:
    """R10.13 — `namespaced` puts the machine's namespace in front of a name."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("incidents", "sandbox.incidents"),
            ("incident-audit.extract", "sandbox.incident-audit.extract"),
            ("incident-audit.judge.root_cause", "sandbox.incident-audit.judge.root_cause"),
        ],
    )
    def test_a_namespace_goes_in_front_of_a_dataset_and_a_prompt_name(self, name, expected):
        """Rows 1 and 2: the one where a dataset and a prompt are namespaced alike."""
        from dossier.domain.tracking import namespaced

        assert namespaced(name, "sandbox") == expected

    def test_an_empty_namespace_leaves_the_name_exactly_as_composed(self):
        """Counter-example (row 5): the one where nobody who never set it sees a change."""
        from dossier.domain.tracking import namespaced

        assert namespaced("incidents", "") == "incidents"
