"""R3.13 — every input value names the document it came from, in `per_file` and
`per_part` as well as `aggregate`.

`_input_values` is the function that decides what a placeholder holds. Tested
directly because the property is about one substitution and nothing else: the
acceptance tests for R3.12 and R6.3 exercise the paths around it, and a model
that must carry a key it was never shown is a defect visible right here.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def step():
    """An `extract` step reading `documents`, as every spec example writes it."""
    from dossier.domain.pipeline import StepConfig

    return StepConfig(
        id="extract", prompt="prompts/01_extract.md", input=["documents"], mode="per_file"
    )


@pytest.fixture
def resolved():
    from dossier.domain.resolution import ResolvedStep

    return ResolvedStep(
        id="extract",
        inputs=["documents"],
        mode="per_file",
        prompt_hash="0" * 64,
        schema_hash=None,
        generated_schema_hash=None,
    )


def _values(step, resolved, *, aggregate, by_kind, produced=None, document="PLAY-1001.md"):
    from dossier.application.run import _input_values

    return _input_values(
        declared=step,
        resolved=resolved,
        document=document,
        documents=["PLAY-1001.md", "PLAY-1002.md"],
        aggregate=aggregate,
        by_kind=by_kind,
        reference={},
        produced=produced or {},
    )


class TestEveryInputValueNamesItsDocument:
    """R3.13 — a stage is shown the key it is asked to carry."""

    def test_a_per_file_value_wraps_the_one_document_it_is_about(self, step, resolved):
        """Row 1 — the key the model must answer with is in the prompt it is given."""
        values = _values(
            step,
            resolved,
            aggregate=False,
            by_kind={"markdown": {"PLAY-1001.md": "**Severity:** major"}},
        )

        assert values["documents"] == (
            '<document key="PLAY-1001.md">**Severity:** major</document>'
        )

    def test_a_per_file_value_holds_only_its_own_document(self, step, resolved):
        """The half that makes per_file per_file. The other note is not in this call."""
        values = _values(
            step,
            resolved,
            aggregate=False,
            by_kind={"markdown": {"PLAY-1001.md": "major", "PLAY-1002.md": "minor"}},
        )

        assert "PLAY-1002.md" not in values["documents"]

    def test_an_earlier_step_s_output_is_wrapped_too(self):
        """Row 3 — a citation needs a key whatever produced the text it cites."""
        from dossier.domain.pipeline import StepConfig
        from dossier.domain.resolution import ResolvedStep

        declared = StepConfig(
            id="verify",
            prompt="prompts/02_verify.md",
            input=["documents", "extract"],
            mode="per_file",
        )
        resolved = ResolvedStep(
            id="verify",
            inputs=["documents", "extract"],
            mode="per_file",
            prompt_hash="0" * 64,
            schema_hash=None,
            generated_schema_hash=None,
        )

        values = _values(
            declared,
            resolved,
            aggregate=False,
            by_kind={"markdown": {"PLAY-1001.md": "the note"}},
            produced={"extract": {"PLAY-1001.md": '{"document": "PLAY-1001.md"}'}},
        )

        assert values["documents"] == '<document key="PLAY-1001.md">the note</document>'
        assert values["extract"] == (
            '<document key="PLAY-1001.md">{"document": "PLAY-1001.md"}</document>'
        )

    def test_an_aggregate_value_is_unchanged(self, step, resolved):
        """Row 6 — this rule is the aggregate branch's shape reaching the others."""
        values = _values(
            step,
            resolved,
            aggregate=True,
            by_kind={"markdown": {"PLAY-1001.md": "major", "PLAY-1002.md": "minor"}},
        )

        assert values["documents"] == (
            '<document key="PLAY-1001.md">major</document>\n'
            '<document key="PLAY-1002.md">minor</document>'
        )

    def test_a_document_the_step_produced_nothing_for_stays_empty(self, step, resolved):
        """A blank value invites an answer about a document nobody read.

        Absent rather than an empty wrapper, exactly as `_joined` leaves it out:
        `<document key="PLAY-1001.md"></document>` is a document that exists and
        says nothing, which is a different claim from one that was not read.
        """
        values = _values(step, resolved, aggregate=False, by_kind={"markdown": {}})

        assert values["documents"] == ""

    def test_execute_and_replay_render_the_same_value(self, step, resolved):
        """The invariant that makes a run reproducible at all (R4.14).

        A replay recomposes its keys from these values rather than reading them
        out of the manifest, so a rendering the two paths disagreed about would
        build a key no run had ever written -- and every run would be
        irreproducible, with `dossier eval` able to score none of them. The
        decision used to be written out twice, once here and once in
        `_replayed_input`, and the two agreeing was something to remember.
        """
        from dossier.application.run import _replayed_input

        text = {"PLAY-1001.md": "**Severity:** major"}

        executed = _values(step, resolved, aggregate=False, by_kind={"markdown": text})
        replayed = _replayed_input(
            target="documents",
            document="PLAY-1001.md",
            documents=["PLAY-1001.md", "PLAY-1002.md"],
            aggregate=False,
            document_text=text,
            produced={},
        )

        assert executed["documents"] == replayed
