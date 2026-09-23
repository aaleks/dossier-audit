"""R10.15 — reading the namespace refuses the variable it replaced.

`namespace(environ)` is the one reader of this machine's namespace: it refuses
the retired `DOSSIER_MLFLOW_PROMPT_PREFIX` by name, checks what it reads
(R10.14), and returns it. Pure, so the rule is proved on a dict.
"""

from __future__ import annotations

import pytest

RETIRED = "DOSSIER_MLFLOW_PROMPT_PREFIX"


class TestTheNamespaceIsReadAndTheRetiredVariableRefused:
    """R10.15 — the retired variable, set to a value, is refused by name."""

    def test_the_retired_variable_is_refused_naming_both(self):
        """Rows 1-2: the one that would have stopped being namespaced without a word."""
        from dossier.domain.tracking import NAMESPACE, namespace

        with pytest.raises(ValueError) as refused:
            namespace({RETIRED: "sandbox"})

        assert RETIRED in str(refused.value)
        assert NAMESPACE in str(refused.value)

    def test_a_blank_retired_variable_is_not_a_decision(self):
        """Counter-example (row 3): the one copied from an old `.env.example`."""
        from dossier.domain.tracking import namespace

        assert namespace({RETIRED: ""}) == ""

    def test_the_namespace_is_read_and_checked(self):
        """R10.13 row 1 and R10.14 row 1, through the same reader."""
        from dossier.domain.tracking import NAMESPACE, namespace

        assert namespace({NAMESPACE: "sandbox"}) == "sandbox"
        with pytest.raises(ValueError, match=NAMESPACE):
            namespace({NAMESPACE: "team/a"})
