"""R8.13 — a pair is answered by the converter `sources.yaml` names for it, and
otherwise by the one claimant that is not opt-in.

`docling-markdown` claims the pair `pdf-markdown` claims. Two claims on one pair
are refused rather than settled by installation order (R8.3), so something has to
say which answers, and it is the workspace: `converters:` in `sources.yaml`. The
decision is made once, over what is installed, and everything downstream still
sees one converter per pair -- which is why selection (R8.3) and the manifest
(R8.9) are called below exactly as they always were.

The rows are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.conversion import Converter, NoConverter, answering, select, used

PDF_MARKDOWN = Converter(
    id="pdf-markdown", version="1.1.0", media_type="application/pdf", kind="markdown"
)
PDF_IMAGES = Converter(
    id="pdf-images", version="0.9.1", media_type="application/pdf", kind="page_images"
)
MARKDOWN_TEXT = Converter(
    id="markdown-text", version="1.0.0", media_type="text/markdown", kind="markdown"
)
DOCLING_MARKDOWN = Converter(
    id="docling-markdown",
    version="1.0.0",
    media_type="application/pdf",
    kind="markdown",
    opt_in=True,
)

INSTALLED = [DOCLING_MARKDOWN, PDF_MARKDOWN, PDF_IMAGES, MARKDOWN_TEXT]


def _converts_ops_114(named: list[str], kinds: list[str] | None = None) -> list[Converter]:
    """Who converts `OPS-114`, a PDF, in a workspace naming `named`."""
    return select(
        media_type="application/pdf",
        kinds=kinds or ["markdown"],
        available=answering(INSTALLED, named=named),
    )


class TestANamedConverterAnswersThePairsItClaims:
    """R8.13 — the workspace names who answers a pair; an opt-in converter answers only then."""

    def test_an_opt_in_converter_answers_nothing_unnamed(self):
        """Row 1: the one where Docling is installed and nobody asked for it.

        R8.3 row 1 reads as it always did. Installing a package must not change
        what a workspace that never mentioned it converts with.
        """
        assert _converts_ops_114(named=[]) == [PDF_MARKDOWN]

    def test_a_named_converter_answers_its_pair(self):
        """Row 2: the one where the workspace names Docling."""
        assert _converts_ops_114(named=["docling-markdown"]) == [DOCLING_MARKDOWN]

    def test_the_manifest_pins_the_named_converter_and_not_the_one_it_displaced(self):
        """Row 2, its second half: what the run used, and only that (R8.9)."""
        pinned = used(
            requests=[("application/pdf", None)],
            available=answering(INSTALLED, named=["docling-markdown"]),
        )

        assert pinned == [DOCLING_MARKDOWN]

    def test_a_name_displaces_a_converter_only_on_the_pairs_it_claims(self):
        """Row 3: the one where the PDF is wanted as text and as page images.

        Docling claims `markdown`, so `pdf-images` still answers `page_images`.
        """
        chosen = _converts_ops_114(
            named=["docling-markdown"], kinds=["markdown", "page_images"]
        )

        assert chosen == [DOCLING_MARKDOWN, PDF_IMAGES]

    def test_a_name_no_installed_converter_has_is_refused_by_name(self):
        """Row 4: the one where `docling-markdown` is misspelt.

        Refused rather than ignored: a misspelt name is otherwise no choice at
        all, and the workspace would convert with `pdf-markdown` while its author
        read `converters: [docling-markdwn]` and believed otherwise.
        """
        with pytest.raises(NoConverter) as error:
            answering(INSTALLED, named=["docling-markdwn"])

        message = str(error.value)
        assert "docling-markdwn" in message
        assert "docling-markdown" in message and "pdf-markdown" in message, message

    def test_two_named_converters_claiming_one_pair_are_refused(self):
        """Row 5: the one where the workspace names both PDF text converters.

        Either answer would be picking by the order a list was written in.
        """
        with pytest.raises(NoConverter) as error:
            answering(INSTALLED, named=["pdf-markdown", "docling-markdown"])

        message = str(error.value)
        assert "application/pdf" in message and "markdown" in message
        assert "pdf-markdown" in message and "docling-markdown" in message, message

    def test_two_claimants_neither_opt_in_are_refused_and_told_how_to_choose(self):
        """Counter-example, row 6: the one where nothing is named and nothing is opt-in.

        Refused as it always was (R8.3). What changed is that a person reading the
        refusal now has something to write that settles it.
        """
        fork = Converter(
            id="pdf-markdown-fork",
            version="2.0.0",
            media_type="application/pdf",
            kind="markdown",
        )

        with pytest.raises(NoConverter) as error:
            select(
                media_type="application/pdf",
                kinds=["markdown"],
                available=answering([PDF_MARKDOWN, fork], named=[]),
            )

        assert "converters:" in str(error.value), str(error.value)

    def test_naming_a_converter_nothing_else_claims_changes_nothing(self):
        """The one where the workspace names `markdown-text`, which answers anyway.

        Naming is not only for opt-in converters; a name on a pair with one
        claimant is the answer that pair already had.
        """
        chosen = select(
            media_type="text/markdown",
            kinds=None,
            available=answering(INSTALLED, named=["markdown-text"]),
        )

        assert chosen == [MARKDOWN_TEXT]
