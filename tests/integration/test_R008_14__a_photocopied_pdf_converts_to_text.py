"""R8.14 — `docling-markdown` OCRs a page only when it has no text layer.

Docling for real, over `INC-4830`'s postmortem as published, photocopied, and
half-photocopied (`tests/scans.py`), and over `PLAY-2002`. Which pages are
OCR'd is decided in `domain` and proved in
`test_R008_14__a_page_is_ocred_only_when_it_has_no_text_layer.py`; what is proved
here is that Docling, set up as the converter sets it up, reads each page back as
text a span can be found in, behind the anchor of the page it is on.

`live`, because it needs `dossier[docling]`, the weights R8.15 names, and about
four minutes. The model folder is Docling's own; a failure naming `hf download`
means the weights are not there yet, and the command in it fetches them.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.scans import photocopy

pytestmark = pytest.mark.live

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
PUBLISHED = FIXTURES / "postmortems" / "pdf" / "INC-4830-postmortem-checkout-tls-expiry.pdf"
PLAY_2002 = FIXTURES / "scans" / "PLAY-2002-photocopy-no-text-layer.pdf"

# Spec 008 R8.14 row 1: on page 2 of three.
ROOT_CAUSE = "Certificate renewal and certificate deployment were two separate processes"
# On page 1, and the word OCR read as `noxthwind` in the spike before the
# direction classifier was turned off -- so its being intact says something.
HOSTNAME = "acq-gw.prod.northwind.internal"

# A second interpreter converting the same bytes, for row 3.
PROBE = """
import sys
sys.path.insert(0, {src!r})
from pathlib import Path
from dossier.infrastructure.converters.docling_markdown import DoclingMarkdownConverter
payload = Path({payload!r}).read_bytes()
Path({out!r}).write_bytes(DoclingMarkdownConverter().convert(payload, {{}}))
"""


@pytest.fixture(scope="module")
def converter():
    """One converter for the module, so Docling loads its models once.

    Docling is looked for here rather than at import, so that collecting the
    default suite never imports it.
    """
    pytest.importorskip("docling", reason="needs dossier[docling]")
    from dossier.infrastructure.converters.docling_markdown import DoclingMarkdownConverter

    return DoclingMarkdownConverter()


def _pages(artifact: bytes) -> list[str]:
    from dossier.domain.grounding import split_pages

    return split_pages(artifact.decode("utf-8"))


class TestAPhotocopiedPdfConvertsToText:
    """R8.14 — a page with no text layer is read by OCR, and every page is behind its anchor."""

    def test_every_page_of_a_photocopy_is_read(self, converter):
        """Row 1: the one where all three pages are pictures."""
        pages = _pages(converter.convert(photocopy(PUBLISHED.read_bytes()), {}))

        assert len(pages) == 3
        assert ROOT_CAUSE in pages[1], pages[1]

    def test_a_half_photocopy_is_read_page_by_page(self, converter):
        """Row 2: the one where page 1 kept its text layer and pages 2 and 3 did not."""
        pages = _pages(converter.convert(photocopy(PUBLISHED.read_bytes(), keep={1}), {}))

        assert len(pages) == 3
        assert HOSTNAME in pages[0], pages[0]
        assert ROOT_CAUSE in pages[1], pages[1]

    def test_a_photocopy_converts_to_the_same_bytes_in_another_process(
        self, converter, repo_root: Path, tmp_path: Path
    ):
        """Row 3: the one where a second interpreter, elsewhere, reads the same photocopy.

        Another process, working directory and hash seed, so that nothing a
        process carries -- a thread pool's order, a set's, a relative path --
        reaches the artifact (R8.1 row 2). Another machine is spec 008's open
        question 2.
        """
        payload = tmp_path / "INC-4830-photocopied.pdf"
        payload.write_bytes(photocopy(PUBLISHED.read_bytes()))
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        out = tmp_path / "artifact.md"

        subprocess.run(
            [
                sys.executable,
                "-c",
                PROBE.format(src=str(repo_root / "src"), payload=str(payload), out=str(out)),
            ],
            check=True,
            capture_output=True,
            cwd=str(elsewhere),
            env={**os.environ, "PYTHONHASHSEED": "987654"},
        )

        assert out.read_bytes() == converter.convert(payload.read_bytes(), {})

    def test_a_published_pdf_is_read_from_its_text_layer(self, converter):
        """Counter-example, row 5: the one where every page has a text layer."""
        pages = _pages(converter.convert(PUBLISHED.read_bytes(), {}))

        assert len(pages) == 3
        assert HOSTNAME in pages[0], pages[0]
        assert ROOT_CAUSE in pages[1], pages[1]

    def test_a_page_with_no_text_to_find_converts_to_its_anchor(self, converter):
        """Counter-example, row 6: the one where the only picture is 24 pixels of nothing.

        OCR finding no text is a finding rather than a failure, as it is for
        `pdf-markdown`: the document converts, and the artifact says there was
        a page and nothing on it could be read.
        """
        assert converter.convert(PLAY_2002.read_bytes(), {}) == b"<!-- page 1 -->"
