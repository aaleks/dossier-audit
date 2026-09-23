"""R14.10 — the prefix check, on its own, so it can run before any name is composed.

R14.8 row 5 refused `team/a` inside `prompt_name`, which is reached only once a
command is already composing names. Refusing before any work needs the check
without the name.
"""

from __future__ import annotations

import pytest


class TestAPrefixMlflowWouldRejectIsRefusedByName:
    """R14.10 — a prefix MLflow would reject is refused, naming the variable."""

    @pytest.mark.parametrize("prefix", ["team/a", "team:a"])
    def test_a_prefix_mlflow_rejects_is_refused_naming_the_variable(self, prefix: str):
        """Rows 1-4: the one refused before any work, for either character."""
        from dossier.domain.prompts import PROMPT_PREFIX, check_prompt_prefix

        with pytest.raises(ValueError, match=PROMPT_PREFIX):
            check_prompt_prefix(prefix)

    @pytest.mark.parametrize("prefix", ["", "sandbox"])
    def test_an_empty_or_accepted_prefix_passes(self, prefix: str):
        """Counter-example (row 6): the one where the namespace is fine."""
        from dossier.domain.prompts import check_prompt_prefix

        check_prompt_prefix(prefix)
