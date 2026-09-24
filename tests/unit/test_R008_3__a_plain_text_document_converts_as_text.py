"""R8.3 — a converter is selected by the pair `(media type, kind)`.

`text/plain` has been in `MEDIA_TYPES` since the table was written and nothing
claimed it, so a folder holding one `.txt` note stopped the whole run (R8.5).
This is the converter that claims it, proved where the pair is selected.

The rule's own example table is transcribed in
`test_R008_3__converter_is_selected_by_media_type_and_kind.py`. What is added
here is the pair itself.
"""

from __future__ import annotations

import pytest

from dossier.domain.conversion import answering, default_kind, select
from dossier.infrastructure.converters.registry import installed_converters

# What a workspace naming no converter is handed (R8.13): everything installed
# that is not opt-in, which is what `dossier convert` selects from.
INSTALLED = answering(installed_converters(), named=[])


class TestPlainTextIsClaimed:
    """R8.3 — `(text/plain, markdown)` resolves to a converter that ships."""

    def test_a_txt_note_from_a_silent_source_resolves(self):
        """The one where a folder of notes holds a `.txt` beside the `.md`.

        A source declaring no `convert:` gets the fallback kind for `text/plain`,
        which is `markdown` (R8.10 row 3). Before this converter existed that
        pair was unclaimed and the run stopped on it.
        """
        chosen = select(media_type="text/plain", kinds=None, available=INSTALLED)

        assert [c.id for c in chosen] == ["text-plain"]
        assert default_kind("text/plain") == "markdown"

    def test_the_text_is_handed_on_exactly_as_written(self):
        """The one where nothing is reinterpreted on the way through.

        No line-ending normalisation, no stripping, no BOM removal: every one of
        those changes the artifact hash for a file nobody edited, and the
        grounding check searches this exact text (R6.4).
        """
        converter = next(c for c in INSTALLED if c.id == "text-plain")
        payload = b"INC-4821\r\n\r\n  Total exposure CHF 48'200 \n"

        assert converter.convert(payload, {}) == payload

    def test_bytes_that_are_not_text_fail_against_their_own_document(self):
        """Counter-example: the one where the payload was never text at all.

        A `ValueError` here is R8.6's shape -- one document fails with a reason
        and the other nine convert. Raised at the decode rather than carried
        downstream as replacement characters, which would ground a span against
        text no source ever wrote.
        """
        converter = next(c for c in INSTALLED if c.id == "text-plain")

        with pytest.raises(ValueError, match="text-plain"):
            converter.convert(b"\xff\xfe\x00\x00not utf-8", {})
