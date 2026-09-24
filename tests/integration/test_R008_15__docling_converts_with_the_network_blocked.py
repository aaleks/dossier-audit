"""R8.15 — `docling-markdown` never fetches a model.

Row 1, for real: a photocopy converts with every socket refused. Docling's own
default is to download its layout model from Hugging Face the first time it is
needed; the converter hands it a model folder instead, and this is the proof that
nothing Docling or RapidOCR does on the way reaches past it.

`live` like every test that runs Docling, and so it keeps its sockets unless it
takes them away itself -- which it does, after the libraries are imported,
because refusing sockets before `ssl` is imported breaks the import rather than
a download.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from tests.scans import photocopy

pytestmark = pytest.mark.live

PUBLISHED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "postmortems"
    / "pdf"
    / "INC-4830-postmortem-checkout-tls-expiry.pdf"
)
ROOT_CAUSE = "Certificate renewal and certificate deployment were two separate processes"


class TestDoclingConvertsWithTheNetworkBlocked:
    """R8.15 — the weights come from disk, and nothing is fetched."""

    def test_a_photocopy_converts_with_every_socket_refused(self, monkeypatch):
        """Row 1: the one where Docling is set up and run with no network at all.

        A fresh converter, so that loading the models happens under the block as
        well as reading the pages.
        """
        pytest.importorskip("docling", reason="needs dossier[docling]")
        import docling.document_converter  # noqa: F401 -- imported before the block
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401

        from dossier.domain.grounding import split_pages
        from dossier.infrastructure.converters.docling_markdown import DoclingMarkdownConverter

        payload = photocopy(PUBLISHED.read_bytes())

        def refuse(*args, **kwargs):
            raise AssertionError("docling-markdown opened a socket (R8.15)")

        monkeypatch.setattr(socket, "socket", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)

        pages = split_pages(DoclingMarkdownConverter().convert(payload, {}).decode("utf-8"))

        assert ROOT_CAUSE in pages[1], pages[1]
