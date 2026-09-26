"""R8.26 — `convert:` may map a media type to its kinds, and a document whose
media type the map does not name gets its default.

A list under `convert:` asks every document the source holds for every kind in
it. A map says which documents a kind is for. A media type the map names is
declared, and follows R8.24; one it does not name is left to the default table
(R8.10), and follows R8.25.

`select` reads either shape, so a conversion and a manifest (`used`) ask one
function what a document wants, and cannot disagree about it.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dossier.domain.conversion import NoConverter, UnclaimedDefault, kinds_for, select
from dossier.domain.pipeline import SourceConfig, StepConfig
from dossier.domain.resolution import check_kinds

PDF = "application/pdf"
PAGE = "application/vnd.dossier.confluence-page+json"
EXPORT_BOTH = {PDF: ["markdown", "page_images"]}


class Converter:
    def __init__(self, id: str, media_type: str, kind: str):
        self.id, self.version, self.media_type, self.kind = id, "1.0.0", media_type, kind

    def convert(self, payload: bytes, options) -> bytes:
        return payload


PDF_MARKDOWN = Converter("pdf-markdown", PDF, "markdown")
PDF_IMAGES = Converter("pdf-images", PDF, "page_images")
PAGE_MARKDOWN = Converter("confluence-page-markdown", PAGE, "markdown")
INSTALLED = [PDF_MARKDOWN, PDF_IMAGES, PAGE_MARKDOWN]


class TestTheMapSaysWhichDocumentsAKindIsFor:
    """R8.26 — a named media type gets its kinds, and any other its default."""

    def test_the_export_gets_both_kinds_and_the_page_its_default(self):
        """Row 1: the one where `page_images` is asked of the export alone.

        `81920114.pdf` is `application/pdf`, which the map names. The page
        `81920114` is not, so it gets `markdown`, its default, and nothing is
        asked of it that nothing can make.
        """
        export = select(media_type=PDF, kinds=EXPORT_BOTH, available=INSTALLED)
        page = select(media_type=PAGE, kinds=EXPORT_BOTH, available=INSTALLED)

        assert [c.id for c in export] == ["pdf-markdown", "pdf-images"]
        assert [c.id for c in page] == ["confluence-page-markdown"]

    def test_kinds_for_reads_either_shape(self):
        """The one where the two shapes are one question: what was declared here.

        `None` means nothing was declared for this media type, and the default
        table answers (R8.10). A list is declared for every media type.
        """
        assert kinds_for(EXPORT_BOTH, PDF) == ["markdown", "page_images"]
        assert kinds_for(EXPORT_BOTH, PAGE) is None
        assert kinds_for(["markdown"], PAGE) == ["markdown"]
        assert kinds_for(None, PDF) is None

    def test_a_step_reading_page_images_resolves_against_the_map(self):
        """Row 2: the one where the source was told to make `page_images`.

        For one media type of the ones it holds, which is all R4.13 can know
        before a byte is fetched.
        """
        source = SourceConfig(id="incidents-mixed", type="folder", convert=EXPORT_BOTH)
        step = StepConfig(
            id="extract",
            prompt="prompts/01_extract.md",
            input="documents@page_images",
            mode="per_part",
            output="schemas/incident.yaml",
        )

        check_kinds(steps=[step], sources=[source], reference=[])

    def test_a_kind_the_map_never_names_is_still_refused_at_resolution(self):
        """The one where the map declares kinds, and not the one a step reads (R4.13)."""
        source = SourceConfig(id="incidents-mixed", type="folder", convert={PDF: ["markdown"]})
        step = StepConfig(
            id="extract",
            prompt="prompts/01_extract.md",
            input="documents@page_images",
            mode="per_part",
            output="schemas/incident.yaml",
        )

        with pytest.raises(ValueError, match="page_images"):
            check_kinds(steps=[step], sources=[source], reference=[])

    def test_a_media_type_the_map_does_not_name_fails_on_its_own(self):
        """Row 3: the one where the JSON's kind was the default.

        The map names `application/pdf`, so `PLAY-4006-indexer-alerts.json` was
        not declared, and nothing claiming its default pair is its own failure
        (R8.25).
        """
        with pytest.raises(UnclaimedDefault):
            select(
                media_type="application/json", kinds={PDF: ["markdown"]}, available=INSTALLED
            )

    def test_a_kind_the_map_names_is_declared(self):
        """Row 4: the one where the map asks for a pair nothing claims (R8.24)."""
        with pytest.raises(NoConverter) as error:
            select(media_type=PDF, kinds={PDF: ["page_images"]}, available=[PDF_MARKDOWN])

        assert not isinstance(error.value, UnclaimedDefault)

    def test_the_list_form_asks_every_document(self):
        """Counter-example (row 5): the one where the list is what it always was."""
        with pytest.raises(NoConverter) as error:
            select(media_type=PAGE, kinds=["markdown", "page_images"], available=INSTALLED)

        assert not isinstance(error.value, UnclaimedDefault)
        assert f"({PAGE!r}, 'page_images')" in str(error.value)

    def test_a_file_extension_is_not_a_media_type(self):
        """Counter-example (row 6): the one where `pdf` is written for `application/pdf`.

        Refused at load, naming it: the snapshot's media type selects a
        converter, and a file extension is not evidence about content (R8.3).
        """
        with pytest.raises(ValidationError, match="'pdf'"):
            SourceConfig(id="incidents-mixed", type="folder", convert={"pdf": ["page_images"]})
