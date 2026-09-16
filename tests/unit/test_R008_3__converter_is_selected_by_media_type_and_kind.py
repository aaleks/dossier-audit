"""R8.3 — a converter is selected by the pair `(media type, kind)`, never by file extension.

Media type comes from the snapshot; kind comes from the source's `convert:` list,
or is that media type's default when the source declares none.

Neither half alone is enough, and both halves failing alone is why this is one
rule rather than two. Media type cannot express that one PDF is wanted as text
and another as page images. A declared kind cannot say what the bytes actually
are. The pair can say both.

The rows below are the rule's example table, transcribed. The converters are the
canonical three in `specs/_fixtures.md`.
"""

from __future__ import annotations

import pytest

from dossier.domain.conversion import Converter, select

PDF_MARKDOWN = Converter(
    id="pdf-markdown", version="1.3.0", media_type="application/pdf", kind="markdown"
)
PDF_IMAGES = Converter(
    id="pdf-images", version="0.9.1", media_type="application/pdf", kind="page_images"
)
MARKDOWN_TEXT = Converter(
    id="markdown-text", version="1.0.0", media_type="text/markdown", kind="markdown"
)

INSTALLED = [PDF_MARKDOWN, PDF_IMAGES, MARKDOWN_TEXT]


class TestConverterSelection:
    """R8.3 — the pair decides, and nothing else does."""

    def test_a_declared_kind_picks_its_converter(self):
        """Example 1: the one where `OPS-114` is wanted as text."""
        chosen = select(media_type="application/pdf", kinds=["markdown"], available=INSTALLED)

        assert chosen == [PDF_MARKDOWN]

    def test_two_declared_kinds_pick_two_converters(self):
        """Example 2: the one where a page is wanted as both text and images.

        Two converters, so two artifacts and two keys (R8.4). Order follows the
        source's declaration, because a caller that sorted them would make the
        `convert:` list unreadable against the artifacts it produced.
        """
        chosen = select(
            media_type="application/pdf",
            kinds=["markdown", "page_images"],
            available=INSTALLED,
        )

        assert chosen == [PDF_MARKDOWN, PDF_IMAGES]

    def test_a_source_declaring_nothing_gets_the_default_kind(self):
        """Example 3: the one where `audit-note.pdf` comes from a plain folder.

        A folder source declares no `convert:` -- it declares nothing at all, by
        design (R2.10). It still has to convert, so the media type's default kind
        answers for it.
        """
        chosen = select(media_type="application/pdf", kinds=None, available=INSTALLED)

        assert chosen == [PDF_MARKDOWN]

    def test_the_bytes_decide_and_the_filename_does_not(self):
        """Counter-example (row 4): the one named `notes.pdf` that is markdown.

        The media type travels on the snapshot, which the connector set from what
        it actually received (spec 001). A selector that read the extension would
        hand markdown bytes to a PDF parser and fail somewhere far from the cause.
        """
        chosen = select(media_type="text/markdown", kinds=None, available=INSTALLED)

        assert chosen == [MARKDOWN_TEXT]
        assert chosen[0].id != PDF_MARKDOWN.id

    def test_the_same_kind_under_a_different_media_type_is_a_different_converter(self):
        """The one where `markdown` means two different things.

        `pdf-markdown` and `markdown-text` both produce the kind `markdown`. Only
        the pair separates them, which is the claim this rule makes.
        """
        from_pdf = select(media_type="application/pdf", kinds=["markdown"], available=INSTALLED)
        from_md = select(media_type="text/markdown", kinds=["markdown"], available=INSTALLED)

        assert from_pdf != from_md

    def test_an_unclaimed_pair_is_refused_rather_than_guessed(self):
        """The one where the pair exists on neither axis.

        `application/pdf` is claimed and `page_images` is claimed, but a
        `text/markdown` source asking for page images is a pair nobody registered.
        Returning nothing would let the document silently vanish from the run;
        the error is what R8.5 turns into a stopped run.
        """
        with pytest.raises(ValueError) as error:
            select(media_type="text/markdown", kinds=["page_images"], available=INSTALLED)

        message = str(error.value)
        assert "text/markdown" in message
        assert "page_images" in message

    def test_the_error_lists_what_is_available(self):
        """The one where the message is an instruction, not a complaint.

        Someone hitting this has usually not installed a package. Naming the
        claimed pairs is what turns the message into the next thing to do --
        the shape `UnknownSourceType` already uses for connectors (R1.7).
        """
        with pytest.raises(ValueError) as error:
            select(media_type="application/zip", kinds=None, available=INSTALLED)

        message = str(error.value)
        assert "application/zip" in message
        assert "application/pdf" in message

    def test_selection_does_not_depend_on_the_order_converters_were_installed(self):
        """The one where an entry point group's order must not leak.

        `entry_points()` returns whatever order the environment produces. Two
        machines with the same packages must select the same converter (R5.6).
        """
        forwards = select(media_type="application/pdf", kinds=["markdown"], available=INSTALLED)
        backwards = select(
            media_type="application/pdf",
            kinds=["markdown"],
            available=list(reversed(INSTALLED)),
        )

        assert forwards == backwards


class TestADuplicatedPairIsRefused:
    """R8.3 — a pair matches at most one converter, and that is now enforced.

    Found by `/quality`. `installed_converters()` sorts by `(media_type, kind)`,
    which does not break a tie between two converters claiming the *same* pair --
    their relative order is whatever `entry_points()` returned, which is
    installation order on that machine. The lookup then silently kept the last.

    The winner's id and version are in `K_convert`, so two machines with the same
    packages installed in a different order computed different convert keys and
    different stage keys above them. A registry docstring assumed the pair was
    unique; nothing checked.
    """

    def test_two_converters_claiming_one_pair_are_refused_by_name(self):
        """The one where the ambiguity is reported rather than resolved.

        Picking either would be picking by installation order. Refusing names
        both, so whoever installed the second one can uninstall it or the
        maintainers can decide which claim is wrong.
        """
        rival = Converter(
            id="pdf-markdown-fork",
            version="2.0.0",
            media_type="application/pdf",
            kind="markdown",
        )

        with pytest.raises(ValueError) as error:
            select(
                media_type="application/pdf",
                kinds=["markdown"],
                available=[PDF_MARKDOWN, rival],
            )

        message = str(error.value)
        assert "pdf-markdown" in message and "pdf-markdown-fork" in message
        assert "application/pdf" in message

    def test_the_refusal_does_not_depend_on_which_order_they_arrived(self):
        """The one that makes the refusal itself deterministic.

        A check that only fired for one ordering would reproduce the original bug
        in a new place -- half the machines erroring and half quietly picking.
        """
        rival = Converter(
            id="pdf-markdown-fork",
            version="2.0.0",
            media_type="application/pdf",
            kind="markdown",
        )

        for order in ([PDF_MARKDOWN, rival], [rival, PDF_MARKDOWN]):
            with pytest.raises(ValueError) as error:
                select(media_type="application/pdf", kinds=["markdown"], available=order)
            assert "pdf-markdown-fork" in str(error.value)

    def test_the_same_converter_listed_twice_is_not_a_conflict(self):
        """The counter-example: one converter is not two.

        A package discovered through two entry-point paths is the same claim
        made twice, not a disagreement. Refusing it would break an installation
        that is merely untidy.
        """
        chosen = select(
            media_type="application/pdf",
            kinds=["markdown"],
            available=[PDF_MARKDOWN, PDF_MARKDOWN],
        )

        assert chosen == [PDF_MARKDOWN]
