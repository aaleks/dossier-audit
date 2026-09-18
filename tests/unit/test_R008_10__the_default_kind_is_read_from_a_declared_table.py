"""R8.10 — the default kind is read from a declared table.

R8.3 says a source declaring no `convert:` gets "the default kind for that media
type" and leaves the table to be written. One constant answered for every media
type instead, which is right for text and wrong for the first media type with no
text in it.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from dossier.domain.conversion import default_kind


class TestTheDefaultKindComesFromTheTable:
    """R8.10 — a declared table, with `markdown` as the fallback."""

    def test_an_image_defaults_to_the_kind_a_stage_can_actually_be_given(self):
        """Example 2: the one where there is no text layer to read.

        `page_images`, not `markdown`. An image has no text in it to convert,
        so resolving it to the text kind names a pair that cannot honestly be
        claimed -- and R8.5 then sends the reader off to write that converter.
        """
        assert default_kind("image/png") == "page_images"
