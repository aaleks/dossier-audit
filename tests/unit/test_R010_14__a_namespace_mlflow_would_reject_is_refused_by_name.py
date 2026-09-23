"""R10.14 — the namespace check, on its own, so it runs before any name is composed.

R14.10's unit test, reclaimed for the variable that replaced R14.8's. The
refusal names `DOSSIER_MLFLOW_NAMESPACE`: the person reading it never typed the
namespace into the command, so the message has to say which setting to change.
"""

from __future__ import annotations

import pytest


class TestANamespaceMlflowWouldRejectIsRefusedByName:
    """R10.14 — a namespace MLflow would reject is refused, naming the variable."""

    @pytest.mark.parametrize("namespace", ["team/a", "team:a"])
    def test_a_namespace_mlflow_rejects_is_refused_naming_the_variable(self, namespace: str):
        """Rows 1-5: the one refused before any work, for either character."""
        from dossier.domain.tracking import NAMESPACE, check_namespace

        with pytest.raises(ValueError, match=NAMESPACE):
            check_namespace(namespace)

    @pytest.mark.parametrize("namespace", ["", "sandbox"])
    def test_an_empty_or_accepted_namespace_passes(self, namespace: str):
        """Counter-example (row 7): the one where the namespace is fine."""
        from dossier.domain.tracking import check_namespace

        check_namespace(namespace)
