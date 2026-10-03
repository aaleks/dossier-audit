"""R21.10 — the `presidio` masker never fetches a model: one that is missing fails
naming the command that installs it.

Presidio's own path for a model it cannot find is `spacy.cli.download`, which
fetches from GitHub and then runs `pip` in a subprocess -- a network call from a
package right of the hash boundary (R0.19), and one no import walk can see. So
the masker checks each model is installed at its pin before anything loads it.

Proved offline: what is installed is what `importlib.metadata` reports, and the
test says what that is. `spacy.cli.download` is replaced with something that
fails the test if it is ever called, and the autouse fixture blocks sockets.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

DECLARATION = {
    "masker": "presidio",
    "languages": ["en", "it"],
    "score_threshold": 0.5,
    "entities": ["PERSON"],
}


def _installed(versions: dict[str, str]):
    """`importlib.metadata.version` as an installation holding exactly `versions`."""

    def version(name: str) -> str:
        if name not in versions:
            raise PackageNotFoundError(name)
        return versions[name]

    return version


@pytest.fixture
def masker(monkeypatch):
    """The masker, with `spacy.cli.download` made to fail the test if it is reached."""
    pytest.importorskip("spacy")
    import spacy.cli

    import dossier.infrastructure.maskers.presidio as presidio
    from dossier.domain.masking import MaskingDeclaration

    def fetched(*args, **kwargs):
        raise AssertionError(f"spacy.cli.download was called: {args}")

    monkeypatch.setattr(spacy.cli, "download", fetched)
    return presidio, presidio.PresidioMasker(MaskingDeclaration(**DECLARATION))


class TestPresidioNeverFetchesAModel:
    """R21.10 — a missing model stops the run, naming what installs it; nothing is fetched."""

    def test_a_missing_model_fails_naming_it_and_the_install_command(self, masker, monkeypatch):
        """Row 1: the one where `it_core_news_lg` is not installed and a document is Italian."""
        from dossier.domain.masking import MaskerUnavailable

        presidio, built = masker
        monkeypatch.setattr(
            presidio, "installed_version", _installed({"en_core_web_lg": "3.8.0"})
        )

        with pytest.raises(MaskerUnavailable) as raised:
            built.detect("La cliente ha chiamato.", language="it")

        message = str(raised.value)
        assert "it_core_news_lg 3.8.0" in message
        assert "is not installed" in message
        assert "uv sync --extra masking --extra masking-models" in message

    def test_a_model_at_another_version_fails_naming_both_versions(self, masker, monkeypatch):
        """Row 2: the one where `de_core_news_lg` is installed at 3.7.1, where 3.8.0 is pinned.

        The right name at the wrong version is the case nothing else would
        see: a different model under the masker's unchanged version.
        """
        from dossier.domain.masking import MaskerUnavailable

        presidio, built = masker
        monkeypatch.setattr(
            presidio, "installed_version", _installed({"de_core_news_lg": "3.7.1"})
        )

        with pytest.raises(MaskerUnavailable) as raised:
            built.detect("Die Kundin rief an.", language="de")

        assert "de_core_news_lg 3.8.0" in str(raised.value)
        assert "is installed at 3.7.1" in str(raised.value)

    def test_a_model_is_needed_only_by_a_document_read_in_its_language(
        self, masker, monkeypatch
    ):
        """Row 3, a counter-example: the one where Italian is declared and never read.

        Building the masker checks no model, and an English document asks only
        for the English one: `it_core_news_lg` missing stops nothing until a
        document is read in Italian.
        """
        presidio, _ = masker
        monkeypatch.setattr(
            presidio, "installed_version", _installed({"en_core_web_lg": "3.8.0"})
        )

        assert presidio._checked("en") == "en_core_web_lg"
