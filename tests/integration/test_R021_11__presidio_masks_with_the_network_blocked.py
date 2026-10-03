"""R21.11 — the `presidio` masker masks with every network connection refused.

Two of Presidio's defaults reach the network from right of the hash boundary,
and the boundary's import walk sees neither (R0.19): `spacy.cli.download` for a
model it cannot find, and `tldextract`, which Presidio's e-mail recogniser asks
about every address, fetching the public suffix list on a machine that has
never fetched it. Each is refused with a connection *attempt* recorded rather
than merely failed: `tldextract` swallows a failed fetch and falls back to its
bundled list, so a test that only watched for errors would pass while the
masker kept trying to phone home.

`live`: it needs the English model. The machine this runs on may already hold
a suffix list in its cache, so the test first installs the extractor a clean
machine has -- one with an empty cache, which would fetch -- and checks the
masker replaces it.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

PLAY_6001 = (
    Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "cid" / "PLAY-6001.md"
)
DECLARATION = {
    "masker": "presidio",
    "languages": ["en"],
    "score_threshold": 0.5,
    "entities": ["PERSON", "EMAIL_ADDRESS", "URL"],
}


@pytest.fixture
def attempts(monkeypatch, tmp_path) -> list[str]:
    """Every connection or name lookup tried, each refused; and a clean machine's extractor."""
    import tldextract
    import tldextract.tldextract as extractor

    tried: list[str] = []

    def refuse(what: str):
        def refused(*args, **kwargs):
            tried.append(f"{what} {args[:1]}")
            raise OSError(f"network refused in this test: {what}")

        return refused

    monkeypatch.setattr(socket, "getaddrinfo", refuse("getaddrinfo"))
    monkeypatch.setattr(socket, "create_connection", refuse("create_connection"))
    monkeypatch.setattr(socket.socket, "connect", refuse("connect"))
    # What a machine that has never fetched a suffix list holds: an extractor
    # with an empty cache, which fetches on its first address.
    monkeypatch.setattr(
        extractor, "TLD_EXTRACTOR", tldextract.TLDExtract(cache_dir=str(tmp_path / "suffixes"))
    )
    return tried


def _masked(text: str) -> str:
    from dossier.domain.masking import Masking, MaskingDeclaration, mask
    from dossier.infrastructure.maskers.presidio import PresidioMasker

    declaration = MaskingDeclaration(**DECLARATION)
    masker = PresidioMasker(declaration)
    masked, _ = mask(
        text,
        masker.detect(text, language="en"),
        Masking(declaration=declaration, declaration_hash="0" * 64),
    )
    return masked


class TestPresidioMasksWithTheNetworkBlocked:
    """R21.11 — masked, and nothing tried: no model fetched, no suffix list fetched."""

    def test_an_address_and_a_url_are_masked_with_no_attempt_to_connect(self, attempts):
        """Row 1: the one where every connection is refused and the cache is empty."""
        text = PLAY_6001.read_text(encoding="utf-8")

        masked = _masked(text)

        assert "erika.mustermann@example.ch" not in masked
        assert "[EMAIL_ADDRESS_1]" in masked
        assert "https://wiki.example.ch" not in masked
        assert attempts == []

    def test_two_maskings_write_the_same_bytes(self, attempts):
        """Row 2: the one where the bundled list is read every time and none is cached."""
        text = PLAY_6001.read_text(encoding="utf-8")

        assert _masked(text) == _masked(text)
        assert attempts == []

    def test_presidio_never_builds_an_engine_that_loads_its_own_model(
        self, attempts, monkeypatch
    ):
        """Row 3, a counter-example: the one where Presidio's own construction is not used.

        `SpacyNlpEngine.load` is the road to `spacy.cli.download`. The masker
        hands Presidio a loaded engine, so neither is ever called.
        """
        import spacy.cli
        from presidio_analyzer.nlp_engine import SpacyNlpEngine

        called: list[str] = []
        monkeypatch.setattr(spacy.cli, "download", lambda *a, **k: called.append("download"))
        monkeypatch.setattr(SpacyNlpEngine, "load", lambda self: called.append("load"))

        _masked(PLAY_6001.read_text(encoding="utf-8"))

        assert called == []
        assert attempts == []
