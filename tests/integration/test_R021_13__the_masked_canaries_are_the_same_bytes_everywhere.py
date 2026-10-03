"""R21.13 — the masked canaries are the same bytes on every machine.

A masked view's hash is in every stage key over it, and R0.4 says a key is the
same on any machine. Presidio scores each recogniser with a constant, but which
spans spaCy's statistical models find is a computation over floats, so it is
checked rather than assumed: the four canary notes, masked here, must hash to
the SHA-256s pinned below, as a PNG part's do (R8.29). The hashes were taken on
Windows (Python 3.13) and confirmed in `python:3.12-slim` on Linux, with the
same pins and model wheels.

`live`: it needs the four models.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "cid"
LANGUAGES = ["en", "de", "fr", "it"]
DECLARATION = {
    "masker": "presidio",
    "languages": LANGUAGES,
    "score_threshold": 0.5,
    "entities": [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "CREDIT_CARD",
        "CH_AHV",
        "CLIENT_NUMBER",
    ],
    "patterns": {
        "CH_AHV": {
            "regex": r"\b756[.\s]?\d{4}[.\s]?\d{4}[.\s]?\d{2}\b",
            "score": 0.5,
            "context": ["ahv", "avs"],
        },
        "CLIENT_NUMBER": {"regex": r"\bCIF \d{4}-\d{6}\b", "score": 0.85},
    },
}
# Each canary note's masked view, by SHA-256 of its UTF-8 bytes.
PINNED = {
    "PLAY-6001.md": "e3a15c94efca3aa8564b2b3c0cbeb58c40d55405b81e95cb6eb9c985b0e755f6",
    "PLAY-6002.md": "98c4feacf8ce1a4e0d0d60ad8337829bc0a49265f3b01bd9fa03ca96b4ef486b",
    "PLAY-6003.md": "419264b7f8121f6063690f11c01a8d4ad976a7aaf93cafe1a1835379926b50d4",
    "PLAY-6004.md": "60acf5424a98a639b02b78c13df880a24ea26a9c8d0d764970394ce6d35ea5e3",
}


def masked_views() -> dict[str, str]:
    """Each canary note's masked view, as `dossier run` would mask it, by file name."""
    from dossier.domain.masking import Masking, MaskingDeclaration, language_of, mask
    from dossier.infrastructure.maskers.presidio import PresidioMasker

    declaration = MaskingDeclaration(**DECLARATION)
    masking = Masking(declaration=declaration, declaration_hash="0" * 64)
    masker = PresidioMasker(declaration)
    views = {}
    for note in sorted(CORPUS.glob("PLAY-600*.md")):
        text = note.read_text(encoding="utf-8")
        language = language_of(text, LANGUAGES)
        views[note.name], _ = mask(text, masker.detect(text, language=language), masking)
    return views


def digests() -> dict[str, str]:
    return {
        name: sha256(view.encode("utf-8")).hexdigest() for name, view in masked_views().items()
    }


class TestTheMaskedCanariesAreTheSameBytesEverywhere:
    """R21.13 — pinned bytes, so a machine that masks differently is found, not trusted."""

    def test_each_masked_view_has_its_pinned_hash(self):
        """Row 1: the one where the four notes are masked on this machine."""
        assert digests() == PINNED

    def test_a_second_masking_in_the_same_process_writes_the_same_bytes(self):
        """Row 3: the one where nothing a process carries, a warm model included, counts."""
        assert digests() == digests()

    def test_a_model_at_another_version_is_refused_before_anything_is_masked(self, monkeypatch):
        """Row 4, a counter-example: the one where `en_core_web_lg` is at another version.

        Never different bytes under the same key: a different model is a
        different masker, and it is refused (R21.10) before it masks anything.
        """
        import dossier.infrastructure.maskers.presidio as presidio
        from dossier.domain.masking import MaskerUnavailable

        monkeypatch.setattr(presidio, "installed_version", lambda name: "3.7.1")

        with pytest.raises(MaskerUnavailable):
            masked_views()


if __name__ == "__main__":
    # Prints the digests for pinning, and for the second machine to compare:
    # `python tests/integration/test_R021_13__...py` inside the container.
    for name, digest in digests().items():
        print(name, digest)
