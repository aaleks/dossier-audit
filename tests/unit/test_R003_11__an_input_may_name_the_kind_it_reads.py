"""R3.11 — a step's input may name the converted kind it reads.

R8.4's fourth counter-example leaves "which kind a stage reads" to spec 003, and
spec 003 never picked it up -- so `page_images` was a real, keyed, invalidatable
artifact that no step could name.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.pipeline import split_kind


class TestAnInputCarriesItsKind:
    """R3.11 — `documents@page_images`, and bare `documents` means `markdown`."""

    def test_a_kind_written_after_an_at_sign_is_read_off_the_input(self):
        """Example 1: the one the whole rule exists for."""
        assert split_kind("documents@page_images") == ("documents", "page_images")

    def test_a_bare_source_keyword_still_means_markdown(self):
        """Example 2: the one where an existing pipeline must not change.

        Every pipeline written before this rule says `documents`, and every one
        of them has to keep resolving to exactly what it resolved to before.
        """
        assert split_kind("documents") == ("documents", "markdown")
        assert split_kind("reference") == ("reference", "markdown")

    def test_the_kind_may_be_written_out_in_full(self):
        """Counter-example (row 5): the one where the default is written down.

        `documents@markdown` is accepted and identical to `documents`. A default
        is a default, not a prohibition -- and an author mixing the two forms in
        one pipeline is being explicit, not wrong.
        """
        assert split_kind("documents@markdown") == split_kind("documents")

    def test_a_step_id_carries_no_kind(self):
        """The one where a step's output is not a conversion.

        `extract` names another step's artifact. It has no media type and no
        converter, so there is no kind to pick -- and returning `markdown` for
        it would be inventing a property the artifact does not have.
        """
        assert split_kind("extract") == ("extract", None)
        assert split_kind("previous") == ("previous", None)

    def test_naming_a_kind_on_a_step_id_is_refused(self):
        """Example 4: the one where the author asked for something meaningless.

        Refused rather than ignored. A silently dropped `@page_images` would
        read, to its author, as though the step were reading page images -- and
        the artifact it actually read would be the right shape to hide it.
        """
        with pytest.raises(ValueError, match="extract"):
            split_kind("extract@page_images")

    def test_an_empty_kind_is_refused(self):
        """The boundary: the one where the `@` was a typo.

        `documents@` is not `documents`. Falling back to the default here would
        turn a typo into a silently different pipeline, which is the one
        outcome a configuration error must never produce (R3.1).
        """
        with pytest.raises(ValueError, match="documents@"):
            split_kind("documents@")


class TestTheKindPicksTheArtifactAStepIsHanded:
    """R3.11 rows 1-3 — the words in the pipeline reach the prompt."""

    def _values(self, declared_input, by_kind):
        from dossier.application.run import _input_values
        from dossier.domain.pipeline import StepConfig
        from dossier.domain.resolution import ResolvedStep

        declared = StepConfig(
            id="describe", prompt="p.md", input=declared_input, mode="per_file"
        )
        inputs = [name.split("@", 1)[0] for name in declared.inputs]
        return _input_values(
            declared=declared,
            resolved=ResolvedStep(id="describe", inputs=inputs, prompt_hash="h"),
            document="INC-4821",
            documents=["INC-4821"],
            aggregate=False,
            by_kind=by_kind,
            produced={},
        )

    BY_KIND = {
        "markdown": {"INC-4821": "the converted text"},
        "captions": {"INC-4821": "a description of the chart"},
    }

    def test_a_qualified_input_is_handed_that_kind(self):
        """Example 1: the one the whole rule exists for."""
        values = self._values("documents@captions", self.BY_KIND)

        assert values["documents@captions"] == "a description of the chart"

    def test_a_bare_input_is_handed_the_markdown_kind(self):
        """Example 2: the one where nothing about an old pipeline changes."""
        values = self._values("documents", self.BY_KIND)

        assert values["documents"] == "the converted text"

    def test_a_step_may_read_two_kinds_of_the_same_source(self):
        """Example 3: the one where a kind is per input rather than per step.

        Both reach the prompt, under their own placeholders. A step that could
        only choose one kind would make `documents@captions` a replacement for
        the document rather than an addition to it.
        """
        values = self._values(["documents", "documents@captions"], self.BY_KIND)

        assert values["documents"] == "the converted text"
        assert values["documents@captions"] == "a description of the chart"
