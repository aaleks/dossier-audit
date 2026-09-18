"""R4.13 — a step naming a kind no source in its set produces stops the run.

R3.11 lets a step name a kind. This is the check that the kind is one the
sources were actually told to make, and it runs at resolution: it is knowable
from the configuration alone, before a single byte is fetched.

The rows below are the rule's example table, transcribed. The CLI half -- that
nothing ran and no run directory exists -- is in
`tests/acceptance/test_R004_13__a_kind_no_source_produces_stops_the_run.py`.
"""

from __future__ import annotations

import pytest

from dossier.domain.pipeline import SourceConfig, StepConfig
from dossier.domain.resolution import check_kinds


def source(source_id: str, convert: list[str] | None = None) -> SourceConfig:
    return SourceConfig(id=source_id, type="folder", convert=convert)


def step(step_id: str, inputs: str | list[str]) -> StepConfig:
    return StepConfig(id=step_id, prompt="p.md", input=inputs, mode="per_file")


MANUAL = "incidents-manual"
JIRA = "incidents-jira"


class TestAKindMustBeOneItsSourcesProduce:
    """R4.13 — checked against `convert:`, at resolution."""

    def test_a_kind_no_source_was_told_to_make_is_refused(self):
        """Example 1: the one where the source was never told to make it.

        The message names all three, because each answers a different question:
        which line of the pipeline, which kind, and which source to go and fix.
        """
        with pytest.raises(ValueError) as raised:
            check_kinds(
                steps=[step("describe", "documents@page_images")],
                sources=[source(MANUAL)],
                reference=[],
            )

        message = str(raised.value)
        assert "describe" in message
        assert "page_images" in message
        assert MANUAL in message
        assert "convert" in message

    def test_a_source_that_declares_the_kind_is_accepted(self):
        """Example 3: the one where `convert:` grants it."""
        check_kinds(
            steps=[step("describe", "documents@page_images")],
            sources=[source(MANUAL, ["markdown", "page_images"])],
            reference=[],
        )

    def test_one_source_of_two_failing_to_supply_it_is_refused(self):
        """Example 4: the one where half the corpus would silently be missing.

        A step reads its *whole* set. A half-answered input is the silent gap
        this rule exists to prevent -- the run would succeed, over fewer
        documents than the author believes, and nothing would say so.
        """
        with pytest.raises(ValueError, match=MANUAL):
            check_kinds(
                steps=[step("describe", "documents@page_images")],
                sources=[source(JIRA, ["markdown", "page_images"]), source(MANUAL)],
                reference=[],
            )

    def test_a_bare_documents_input_is_checked_on_markdown(self):
        """Counter-example (row 5): the one where the kind is implied.

        `documents` is `documents@markdown` (R3.11), so a source declaring
        `convert: [page_images]` cannot answer it. The rule holds on a pipeline
        whose author never typed a kind at all.
        """
        with pytest.raises(ValueError, match="markdown"):
            check_kinds(
                steps=[step("extract", "documents")],
                sources=[source(MANUAL, ["page_images"])],
                reference=[],
            )

    def test_a_silent_source_supplies_the_default_kind(self):
        """The one where declaring nothing is not declaring nothing useful.

        A source with no `convert:` produces its media type's default (R8.10),
        and for every text source that is `markdown`. Refusing bare `documents`
        against a silent source would break every pipeline in existence.
        """
        check_kinds(
            steps=[step("extract", "documents")], sources=[source(MANUAL)], reference=[]
        )

    def test_reference_is_checked_against_the_reference_sources(self):
        """The one where the two source sets are not interchangeable.

        `reference` reads `reference:`, not `sources:`. Checking it against the
        wrong set would accept a pipeline whose reference material cannot supply
        what the step asked for -- and reject one that can.
        """
        with pytest.raises(ValueError, match=JIRA):
            check_kinds(
                steps=[step("verify", ["documents", "reference@page_images"])],
                sources=[source(MANUAL, ["markdown", "page_images"])],
                reference=[source(JIRA)],
            )

    def test_a_step_id_input_is_not_checked_against_any_source(self):
        """Counter-example: the one where there is no source to check against.

        `previous` and a step id name another step's output. They have no kind
        (R3.11) and no source, so there is nothing here to verify.
        """
        check_kinds(
            steps=[step("extract", "documents"), step("verify", ["extract", "previous"])],
            sources=[source(MANUAL)],
            reference=[],
        )
