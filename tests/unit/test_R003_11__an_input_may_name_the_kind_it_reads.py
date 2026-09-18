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
