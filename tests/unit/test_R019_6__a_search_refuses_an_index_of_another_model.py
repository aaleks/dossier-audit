"""R19.6 — a search of an index holding nothing, or embedded with another model
than its declaration's, is refused before the model is asked.

A query vector from one model is meaningless against another's, and the
lengths need not even agree.
"""

from __future__ import annotations

from dossier.domain.search import model_refusal

DECLARED = (
    "ollama:qwen3-embedding:4b-fp16@sha256:"
    "3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
EARLIER = "ollama:qwen3-embedding:0.6b"


class TestASearchRefusesAnIndexOfAnotherModel:
    """R19.6 — the model the index was embedded with is the one the query must be."""

    def test_an_index_embedded_with_another_model_is_refused(self):
        """Row 1 — the one whose declaration changed since the last embed."""
        assert model_refusal("incidents", held=frozenset({EARLIER}), declared=DECLARED) == (
            f"incidents was embedded with {EARLIER}, and is declared with {DECLARED}: "
            "run dossier embed incidents"
        )

    def test_an_index_holding_nothing_is_refused(self):
        """Row 2 — the one never embedded."""
        assert model_refusal("incidents", held=frozenset(), declared=DECLARED) == (
            "incidents holds nothing yet: run dossier embed incidents"
        )

    def test_an_index_part_embedded_with_another_model_is_refused(self):
        """The one an interrupted change left with both."""
        refusal = model_refusal(
            "incidents", held=frozenset({DECLARED, EARLIER}), declared=DECLARED
        )

        assert refusal is not None and refusal.startswith(
            f"incidents was embedded with {EARLIER}, {DECLARED}, and is declared with"
        )

    def test_an_index_of_the_declared_model_is_searched(self):
        """Row 3, counter-example — the one embedded as declared."""
        assert model_refusal("incidents", held=frozenset({DECLARED}), declared=DECLARED) is None
