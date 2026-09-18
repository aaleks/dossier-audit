"""R8.1 — a converted artifact is a pure function of the snapshot bytes.

`pdf-markdown` is exempt from the conformance rows in
`test_R008_1__conversion_is_a_pure_function_of_its_input.py`, which hand each
converter a literal payload and re-run one of them through a subprocess. A PDF
is a hundred kilobytes of binary and does not survive either. The exemption is
declared out loud there; this file is what discharges it.

The corpus is the one in `specs/_fixtures.md`: sixteen fabricated postmortems in
eight different layouts, so extraction is exercised against more than one
document shape rather than against the one PDF someone happened to have.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2", reason="pdf-markdown needs the 'pdf' extra")

from dossier.infrastructure.converters.pdf_markdown import PdfMarkdownConverter

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")

COMPLETE = "INC-4830-postmortem-checkout-tls-expiry.pdf"
SCANS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "scans"
NO_TEXT_LAYER = "PLAY-2002-photocopy-no-text-layer.pdf"

PROBE = textwrap.dedent(
    """
    import hashlib, sys
    sys.path.insert(0, {src!r})
    from dossier.infrastructure.converters.pdf_markdown import PdfMarkdownConverter

    payload = open({pdf!r}, "rb").read()
    artifact = PdfMarkdownConverter().convert(payload, {{}})
    sys.stdout.write(hashlib.sha256(artifact).hexdigest())
    """
)


def documents() -> list[Path]:
    return sorted(CORPUS.glob("*.pdf"))


@pytest.fixture
def converter() -> PdfMarkdownConverter:
    return PdfMarkdownConverter()


class TestAPdfConvertsToTheTextOfItsPages:
    """R8.1 — the same bytes and the same options, the same artifact."""

    def test_the_text_of_the_document_is_what_comes_out(self, converter: PdfMarkdownConverter):
        """The one where a postmortem becomes text a stage can read.

        Asserted on structure -- the incident key and a phrase the fixture was
        written to contain -- rather than on the whole artifact. A byte-for-byte
        expectation would turn every pypdfium2 upgrade into a test edit, and the
        claim here is that the text layer arrives, not what PDFium's kerning
        heuristics do with it.
        """
        artifact = converter.convert((CORPUS / COMPLETE).read_bytes(), {})
        text = artifact.decode("utf-8")

        assert "INC-4830" in text
        assert "TLS" in text
        assert text.count("\r") == 0, "line endings are normalised to LF"

    @pytest.mark.parametrize("pdf", documents(), ids=lambda p: p.stem)
    def test_converting_twice_produces_identical_bytes(
        self, converter: PdfMarkdownConverter, pdf: Path
    ):
        """Example 1: the one where nothing about the second call differs."""
        payload = pdf.read_bytes()

        assert converter.convert(payload, {}) == converter.convert(payload, {})

    def test_two_processes_with_different_environments_agree(self, converter):
        """Example 2: the one where nothing about the machine reaches the output.

        A different `PYTHONHASHSEED` and a different working directory, because
        both are how a conversion stops being byte-identical across machines
        without anything in a diff to explain it (R0.4, R5.6).
        """
        pdf = CORPUS / COMPLETE
        script = PROBE.format(src=REPO_SRC, pdf=str(pdf))

        digests = {
            subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd,
                env={**dict(PATH=""), "PYTHONHASHSEED": seed, "SYSTEMROOT": ""},
            ).stdout
            for cwd, seed in ((CORPUS, "0"), (Path(__file__).parent, "12345"))
        }

        assert len(digests) == 1, "the artifact differs between processes"

    def test_every_page_is_read_not_just_the_first(self, converter: PdfMarkdownConverter):
        """The one where a three-page postmortem loses two of them.

        The separator is what makes this checkable without asserting prose: a
        document PDFium reports as three pages produces two separators, whatever
        the pages say.
        """
        import pypdfium2 as pdfium

        payload = (CORPUS / COMPLETE).read_bytes()
        pages = len(pdfium.PdfDocument(payload))
        text = converter.convert(payload, {}).decode("utf-8")

        assert pages == 3, "the fixture changed; the count below is about it"
        assert text.count("\n\n") >= pages - 1

    def test_each_page_is_introduced_by_its_anchor(self, converter: PdfMarkdownConverter):
        """The one that makes `source.page` derivable at all (R6.14).

        The anchor format is `domain`'s, imported rather than spelled again
        here: a converter writing one spelling while grounding reads another is
        the failure this shares one definition to avoid.
        """
        from dossier.domain.grounding import page_anchor, split_pages

        text = converter.convert((CORPUS / COMPLETE).read_bytes(), {}).decode("utf-8")

        assert text.startswith(page_anchor(1))
        assert page_anchor(3) in text
        assert len(split_pages(text)) == 3

    def test_a_document_with_no_text_layer_still_says_which_pages_it_had(
        self, converter: PdfMarkdownConverter
    ):
        """Counter-example: the one where converting succeeds and finds nothing.

        A photocopy has no text layer, so it converts to its anchors and nothing
        else. That is not a conversion failure -- the document converted, the
        page exists, and the emptiness is the finding. `dossier convert` exists
        to make that visible before a model call is spent on it (spec 008, "The
        command"), which it cannot do if the converter raises.

        The anchor surviving is what lets a later step say *which* page it is
        describing when nothing here could read it.
        """
        from dossier.domain.grounding import page_anchor

        text = converter.convert((SCANS / NO_TEXT_LAYER).read_bytes(), {}).decode("utf-8")

        assert text.strip() == page_anchor(1)

    def test_bytes_that_are_not_a_pdf_fail_against_their_own_document(
        self, converter: PdfMarkdownConverter
    ):
        """Counter-example: the one where the payload was never a PDF.

        `ValueError` is R8.6's shape -- one document fails with a reason and the
        other nine convert. It is deliberately not R8.5's: the pair is claimed
        and the configuration is right, and one input is bad.
        """
        with pytest.raises(ValueError, match="pdf-markdown"):
            converter.convert(b"not a pdf at all", {})
