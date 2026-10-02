"""A photocopied PDF in, text out, through Docling (spec 008, R8.14, R8.15).

`pdf-markdown` reads a PDF's text layer, and a photocopy has none: the artifact
is its anchors and nothing else, and no field in it can ever be grounded. This
converter runs Docling over the document instead -- a page with a text layer read
from it, a page with none read by OCR -- and is opt-in, because it claims the pair
`pdf-markdown` claims and a workspace chooses it by name (R8.13).

**Its models are part of it.** Docling reads a layout model and a table model
from Hugging Face, and by default downloads them the first time it needs them, at
revision `main`. That is the network on the path every artifact is made on
(R0.19), and a floating name deciding what an artifact says. Here the weights are
read from Docling's model folder at the commits pinned below, and every file read
is checked against the SHA-256 recorded for its commit before a page is converted
(R8.15). Where the folder is differs between machines; which bytes it holds does
not, so its location cannot reach an artifact (R8.1).
"""

from __future__ import annotations

import hashlib
import io
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dossier.domain.conversion import ocr_pages
from dossier.domain.grounding import page_anchor
from dossier.infrastructure.converters._pdfium import pdfium as load_pdfium
from dossier.infrastructure.converters.pdf_markdown import PAGE_SEPARATOR

# How much of a weight file is read at a time while it is hashed. The table
# model is two hundred megabytes, and reading it whole to hash it would hold all
# of it in memory beside the model Docling is about to load.
_CHUNK = 1 << 20


@dataclass(frozen=True)
class PinnedModel:
    """A model's weights at one commit, and the hash of every file read from them.

    `commit` is a commit rather than a branch or a tag because a commit cannot be
    moved. `files` are paths inside the repository; only these are checked, since
    only these are read, and a repository's model card is neither.
    """

    repo: str
    commit: str
    files: Mapping[str, str]
    # An `hf download --include` pattern, for a model that is one folder of a
    # larger repository: fetching the rest to read one folder is a download
    # nobody asked for.
    include: str | None = field(default=None)

    @property
    def folder(self) -> str:
        """The folder Docling looks for this model under, inside its model folder."""
        return self.repo.replace("/", "--")

    def fetch(self, models: Path) -> str:
        """The command that puts this commit where the converter reads it."""
        include = f' --include "{self.include}"' if self.include else ""
        return (
            f"hf download {self.repo} --revision {self.commit}{include} "
            f"--local-dir {models / self.folder}"
        )


# Docling's layout model -- headings, paragraphs, tables and pictures found on a
# page -- at the commit `main` pointed to when this converter was written.
# Docling itself pins it to `main`.
LAYOUT = PinnedModel(
    repo="docling-project/docling-layout-heron",
    commit="8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
    files={
        "config.json": "fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d",
        "model.safetensors": "00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c",
        "preprocessor_config.json": (
            "cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1"
        ),
    },
)

# TableFormer, which turns a table the layout model found into rows and cells.
# Docling pins it to the tag `v2.3.0`; this is the commit that tag named.
TABLES = PinnedModel(
    repo="docling-project/docling-models",
    commit="fc0f2d45e2218ea24bce5045f58a389aed16dc23",
    files={
        "model_artifacts/tableformer/accurate/tableformer_accurate.safetensors": (
            "2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9"
        ),
        "model_artifacts/tableformer/accurate/tm_config.json": (
            "984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd"
        ),
    },
    include="model_artifacts/tableformer/accurate/*",
)

MODELS = (LAYOUT, TABLES)


def check_models(models: Path, pinned: Iterable[PinnedModel] = MODELS) -> None:
    """Refuse weights that are missing or not at their pinned commit (R8.15).

    A `ValueError`, so the document fails with this as its reason and the others
    carry on (R8.6). The message is the fix: the command that fetches the right
    commit into the folder it is read from. Nothing is fetched here -- a converter
    that downloaded would be the thing this check exists to prevent.
    """
    for model in pinned:
        for name, expected in sorted(model.files.items()):
            path = models / model.folder / name
            if not path.is_file():
                raise ValueError(
                    f"docling-markdown reads {model.repo} at commit {model.commit[:8]}, "
                    f"and {path} is not there. Nothing is downloaded while converting; "
                    f"fetch it once with:\n  {model.fetch(models)}"
                )
            found = _sha256(path)
            if found != expected:
                raise ValueError(
                    f"docling-markdown reads {model.repo} at commit {model.commit[:8]}, "
                    f"and {path} is not that commit's: SHA-256 {found}, expected "
                    f"{expected}. Fetch the pinned commit with:\n  {model.fetch(models)}"
                )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as weights:
        while chunk := weights.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# How many threads Docling's models run on, fixed rather than read from the
# machine: Docling otherwise takes it from `OMP_NUM_THREADS`, an environment
# variable a converter may not read (R8.1). Measured before R8.14 was written:
# one thread and four produced the same artifact byte for byte, so this is about
# speed and about not asking the environment, never about the output.
THREADS = 4

# RapidOCR's own models, the ONNX files that ship inside its wheel and are pinned
# with it, as PDFium is with pypdfium2. PP-OCRv6 small: the detector finds lines
# of text and the recogniser reads them, its characters held in its own ONNX
# metadata. Named rather than left to RapidOCR, whose defaults for a torch
# engine are *not* in the wheel: asked for them, it downloads them on first use,
# into its own package folder -- found when a fresh install failed on a
# dictionary file the first spike had quietly fetched.
_OCR_MODELS = {
    "det_model_path": "PP-OCRv6_det_small.onnx",
    "rec_model_path": "PP-OCRv6_rec_small.onnx",
    "cls_model_path": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
}


class DoclingMarkdownConverter:
    """`application/pdf` to `markdown` through Docling, with OCR where there is no text."""

    id = "docling-markdown"
    # Raise this whenever output could change for the same input (R5.4). It
    # covers everything the artifact is a function of besides the PDF: the pinned
    # Docling, RapidOCR and onnxruntime of the `docling` extra, the model commits
    # in `MODELS`, and every option below -- the direction classifier off, a page
    # with no text layer OCR'd whole, escaping off, pictures leaving no mark.
    # 1.1.0: Docling's pypdfium2 backend, drawing with PDFium's own fonts, in
    # place of docling-parse, which drew with the machine's (R8.28).
    version = "1.1.0"
    media_type = "application/pdf"
    kind = "markdown"
    # It claims `pdf-markdown`'s pair, so it answers only where a workspace names
    # it (R8.13). Installing the extra changes nothing until then.
    opt_in = True

    def __init__(self, models: Path | None = None) -> None:
        # `None` is Docling's own model folder, found when a PDF is first
        # converted -- which is also when Docling is first imported, so a
        # workspace that names this converter and holds no PDF pays for neither.
        self._models = models
        self._checked: Path | None = None
        self._pipelines: dict[bool, object] = {}

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """Every page, in page order, behind its anchor (R6.14, R8.14).

        A page whose text layer holds no printable character is OCR'd whole; any
        other page is read from its layer, with Docling's own OCR reading the
        pictures on it. Which is which is decided in `domain` (`ocr_pages`).
        """
        models = self._models if self._models is not None else _docling_models(self.id)
        if self._checked != models:
            check_models(models)
            self._checked = models

        try:
            texts = _text_layers(payload)
            photographed = set(ocr_pages(texts))
            pages = [
                self._read_page(payload, number, models, whole=number in photographed)
                for number in range(1, len(texts) + 1)
            ]
        except Exception as error:
            # R8.6's shape: one document fails with a reason and the others
            # convert. A truncated PDF is a bad input, not a misconfigured
            # pipeline (R8.24).
            raise ValueError(f"{self.id} could not read this PDF: {error}") from error

        text = PAGE_SEPARATOR.join(
            f"{page_anchor(number)}\n{page}".rstrip() for number, page in enumerate(pages, 1)
        )
        return text.encode("utf-8")

    def _read_page(self, payload: bytes, number: int, models: Path, *, whole: bool) -> str:
        from docling.datamodel.base_models import DocumentStream

        # One page at a time, because whether a page is OCR'd whole is decided
        # per page and Docling takes that decision per conversion. The name is a
        # constant: nothing about where the bytes came from may reach the text.
        stream = DocumentStream(name="document.pdf", stream=io.BytesIO(payload))
        document = (
            self._pipeline(models, whole=whole)
            .convert(stream, page_range=(number, number))
            .document
        )
        # Escaping off, because the artifact is text a span is searched in rather
        # than markdown for a renderer: a model quotes `lb_acq_01` and never its
        # escaped form (R6.4). A picture leaves no placeholder, as it leaves
        # nothing in `pdf-markdown`'s artifact either.
        return document.export_to_markdown(
            page_no=number,
            escape_underscores=False,
            escape_html=False,
            image_placeholder="",
        )

    def _pipeline(self, models: Path, *, whole: bool):
        """Docling set up once per OCR mode, with every model read from disk."""
        if whole not in self._pipelines:
            self._pipelines[whole] = _docling(models, whole=whole)
        return self._pipelines[whole]


def _docling_models(converter: str) -> Path:
    """Docling's own model folder, where the `hf download` a failure names puts the weights."""
    try:
        from docling.datamodel.settings import settings
    except ImportError as error:  # pragma: no cover - depends on the install
        raise ValueError(
            f"{converter} needs the 'docling' extra: install dossier[docling]"
        ) from error
    return settings.cache_dir / "models"


def _text_layers(payload: bytes) -> list[str]:
    """Each page's text layer, read as `pdf-markdown` reads it."""
    pdfium = load_pdfium()

    return [
        page.get_textpage().get_text_bounded() or "" for page in pdfium.PdfDocument(payload)
    ]


def _docling(models: Path, *, whole: bool):
    """A Docling converter reading only from `models` and RapidOCR's own wheel.

    `artifacts_path` is what keeps Docling off the network: given one, it looks
    for each model there and nowhere else, and fails rather than downloads when
    one is absent -- which `check_models` has already ruled out (R8.15).
    """
    import rapidocr
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        RapidOcrOptions,
        TableFormerMode,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # RapidOCR announces every model it loads at INFO, through a handler of its
    # own, between the lines `dossier convert` prints. Its logger is set back to
    # INFO each time RapidOCR builds one, and its handler is made once -- so the
    # handler is where the level holds. Transformers draws a progress bar for
    # every model it loads, to the same terminal, for the same nothing.
    from rapidocr.utils.log import logger as ocr_log
    from transformers.utils import logging as transformers_logging

    for handler in ocr_log.handlers:
        handler.setLevel(logging.WARNING)
    transformers_logging.disable_progress_bar()

    ocr_models = Path(rapidocr.__file__).parent / "models"
    options = PdfPipelineOptions(artifacts_path=models, do_ocr=True, do_table_structure=True)
    options.table_structure_options.mode = TableFormerMode.ACCURATE
    options.accelerator_options = AcceleratorOptions(num_threads=THREADS, device="cpu")
    options.ocr_options = RapidOcrOptions(
        backend="onnxruntime",
        # Measured before R8.14 was written: Docling's automatic OCR on a page
        # with no text layer dropped the spaces between words that OCR of the
        # whole page kept, and a span quoted with its spaces is not found in
        # text without them (R6.4).
        force_full_page_ocr=whole,
        # The direction classifier turned one line of a clean, upright scan into
        # noise; off, the line read correctly. A page scanned upside down reads
        # worse for it.
        use_cls=False,
        **{option: str(ocr_models / name) for option, name in _OCR_MODELS.items()},
    )
    # Docling's pypdfium2 backend, not its default. docling-parse draws a page
    # by matching each font a PDF does not embed against the machine's own font
    # folders, falls back to a Windows font by name, and has no setting that
    # stops either; so the same page gave Docling's layout model different
    # pixels on Windows and Linux. PDFium, with its own fonts, draws it the same
    # everywhere (R8.28).
    load_pdfium()
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=options, backend=PyPdfiumDocumentBackend
            )
        }
    )
