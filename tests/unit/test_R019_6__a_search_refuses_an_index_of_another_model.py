"""R19.6 — a search of an index holding nothing, or embedded with another model
than its declaration's, is refused before the model is asked.

A query vector from one model is meaningless against another's, and the
lengths need not even agree.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance import test_R019_8__search_lists_what_answers_the_query as searched
from tests.acceptance.test_R018_7__embed_builds_the_index_from_what_was_synced import _cli
from tests.acceptance.test_R018_11__embed_carries_the_runs_record import INDEX

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


# R19.8's workspace, synced, run and embedded, the index a fake; its fixtures
# shared rather than copied.
issues, embedder, index, run_once, embedded = (
    searched.issues,
    searched.embedder,
    searched.index,
    searched.run_once,
    searched.embedded,
)


def _search(workspace: Path, monkeypatch, *more: str):
    return _cli(workspace, monkeypatch, "search", INDEX, searched.QUERY, *more)


class TestThroughTheCommand:
    """R19.6 — through the command, before the model is asked."""

    def test_an_index_holding_nothing_is_refused(
        self, run_once: Path, monkeypatch, embedder, index
    ):
        """Row 2 — the one never embedded."""
        import dossier.cli.bootstrap as cli

        monkeypatch.setattr(cli, "build_index_search", lambda dsn: index, raising=False)

        result = _search(run_once, monkeypatch)

        assert result.exit_code == 2, result.output
        assert f"{INDEX} holds nothing yet: run dossier embed {INDEX}" in result.stderr
        assert embedder.calls == 0

    def test_an_index_of_another_model_is_refused(
        self, embedded: Path, monkeypatch, embedder, index
    ):
        """Row 1 — the one whose declaration's model changed since the last embed."""
        declared = embedded / "indexes" / f"{INDEX}.yaml"
        text = declared.read_text(encoding="utf-8")
        held = next(line for line in text.splitlines() if line.startswith("embedding_model:"))
        other = held[: -len("0" * 8)] + "0" * 8
        declared.write_text(text.replace(held, other), encoding="utf-8")
        before = embedder.calls

        result = _search(embedded, monkeypatch)

        assert result.exit_code == 2, result.output
        assert f"{INDEX} was embedded with " in result.stderr, result.stderr
        assert f"run dossier embed {INDEX}" in result.stderr
        assert embedder.calls == before

    def test_an_index_of_the_declared_model_is_searched(self, embedded: Path, monkeypatch):
        """Row 3, counter-example — the one embedded as declared."""
        assert _search(embedded, monkeypatch).exit_code == 0
