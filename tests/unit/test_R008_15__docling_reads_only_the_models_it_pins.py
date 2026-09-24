"""R8.15 — `docling-markdown` never fetches a model: one missing, or not at its
pinned commit, fails the document naming the command that fetches it.

Docling's own default is to download its layout model from Hugging Face at `main`
the first time it is needed -- the network on the path every artifact is made on,
and a floating name deciding what the artifact says. The converter reads its
weights from disk instead, and checks every file it reads against the SHA-256
recorded for the commit its version names.

The check is proved here with no Docling installed and no weights on disk: the
rows that need real weights -- a photocopy converting with sockets blocked -- are
the live integration test's. What cannot be faked is the pinned hashes of three
hundred megabytes of weights, so the mechanism is proved over a small model
pinned the same way, and the real pins are checked for what they are.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from dossier.infrastructure.converters.docling_markdown import (
    LAYOUT,
    MODELS,
    TABLES,
    PinnedModel,
    check_models,
)

# Spec 008 R8.15 row 2.
LAYOUT_COMMIT = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"

WEIGHTS = b"the weights at the pinned commit"


def _small_layout(tmp_path: Path, files: dict[str, bytes]) -> PinnedModel:
    """A model pinned as the layout model is, over files a test can write."""
    return PinnedModel(
        repo=LAYOUT.repo,
        commit=LAYOUT.commit,
        files={name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    )


def _hold(models: Path, model: PinnedModel, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        path = models / model.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


class TestDoclingReadsOnlyTheModelsItPins:
    """R8.15 — weights come from disk, at the pinned commit, or the document fails."""

    def test_a_model_held_at_its_pinned_commit_passes(self, tmp_path: Path):
        """Row 1's precondition: the one where the folder holds what was pinned."""
        files = {"config.json": b"{}", "model.safetensors": WEIGHTS}
        model = _small_layout(tmp_path, files)
        _hold(tmp_path, model, files)

        check_models(tmp_path, [model])

    def test_a_missing_model_fails_naming_the_command_that_fetches_it(self, tmp_path: Path):
        """Row 2: the one where the layout model was never fetched.

        The message is the fix. It names the repository, the commit, and the
        `hf download` command that puts the right commit where the converter
        looks -- so the person reading it runs one line rather than learning
        how Docling lays out its model folder.
        """
        with pytest.raises(ValueError) as error:
            check_models(tmp_path, [LAYOUT])

        message = str(error.value)
        assert "docling-project/docling-layout-heron" in message, message
        assert LAYOUT_COMMIT[:8] in message, message
        assert (
            f"hf download docling-project/docling-layout-heron --revision {LAYOUT_COMMIT} "
            f"--local-dir {tmp_path / 'docling-project--docling-layout-heron'}"
        ) in message, message

    def test_weights_from_another_commit_fail_naming_both_hashes(self, tmp_path: Path):
        """Row 3: the one where `model.safetensors` came from a later `main`.

        The folder has the right name and the wrong weights, which is what
        `docling-tools models download` leaves behind the day `main` moves.
        Nothing else would see it: the artifact would simply say something
        else, under a key claiming nothing had changed.
        """
        files = {"config.json": b"{}", "model.safetensors": WEIGHTS}
        model = _small_layout(tmp_path, files)
        _hold(tmp_path, model, {**files, "model.safetensors": b"the weights main holds today"})

        with pytest.raises(ValueError) as error:
            check_models(tmp_path, [model])

        message = str(error.value)
        assert "model.safetensors" in message, message
        assert hashlib.sha256(WEIGHTS).hexdigest() in message, message
        assert hashlib.sha256(b"the weights main holds today").hexdigest() in message, message
        assert f"--revision {LAYOUT_COMMIT}" in message, message

    def test_files_the_converter_does_not_read_are_not_checked(self, tmp_path: Path):
        """Counter-example, row 4: the one where the folder also holds a README and a picture.

        `hf download` fetches a repository's whole tree. What is checked is what
        is read, and a model card is not read.
        """
        files = {"config.json": b"{}", "model.safetensors": WEIGHTS}
        model = _small_layout(tmp_path, files)
        _hold(
            tmp_path,
            model,
            {**files, "README.md": b"# a model card", "docling_heron_400.png": b"\x89PNG"},
        )

        check_models(tmp_path, [model])

    def test_the_table_model_is_fetched_by_the_folder_it_is_read_from(self, tmp_path: Path):
        """The one where the table weights are one folder of a larger repository.

        `docling-project/docling-models` holds more than the table model, and
        fetching all of it to read one folder is a download nobody asked for.
        """
        with pytest.raises(ValueError) as error:
            check_models(tmp_path, [TABLES])

        assert '--include "model_artifacts/tableformer/accurate/*"' in str(error.value)

    def test_every_pin_is_a_commit_and_every_file_a_sha256(self):
        """The one where no pin floats.

        A branch or a tag is a name somebody can move; a commit is not. `main`
        is exactly what Docling pins its layout model to, and what this
        converter exists to not do (R0.6's reasoning, for weights).
        """
        assert [model.repo for model in MODELS] == [
            "docling-project/docling-layout-heron",
            "docling-project/docling-models",
        ]
        assert LAYOUT.commit == LAYOUT_COMMIT
        for model in MODELS:
            assert re.fullmatch(r"[0-9a-f]{40}", model.commit), model
            assert model.files, model
            for name, digest in model.files.items():
                assert re.fullmatch(r"[0-9a-f]{64}", digest), (model.repo, name)


class TestTheConverterChecksBeforeItReads:
    """R8.15 — the check stands between a PDF and Docling, not beside it."""

    def test_a_pdf_with_no_models_held_fails_naming_the_fetch(self, tmp_path: Path):
        """Row 2, through the converter: the one where the folder is empty.

        Refused before a page is read -- and before Docling is imported at all,
        which is why this runs in the default suite without `dossier[docling]`.
        Had the check come after, Docling would have been handed the folder and
        answered with its own error, or, handed none, gone to Hugging Face.
        """
        from dossier.infrastructure.converters.docling_markdown import DoclingMarkdownConverter

        with pytest.raises(ValueError) as error:
            DoclingMarkdownConverter(models=tmp_path).convert(b"%PDF-1.4\n", {})

        message = str(error.value)
        assert f"hf download {LAYOUT.repo} --revision {LAYOUT_COMMIT}" in message, message

    def test_the_converter_is_opt_in_and_claims_the_pdf_text_pair(self):
        """The one where installing the extra changes no workspace (R8.13 row 1)."""
        from dossier.infrastructure.converters.docling_markdown import DoclingMarkdownConverter

        converter = DoclingMarkdownConverter()

        assert (converter.id, converter.media_type, converter.kind) == (
            "docling-markdown",
            "application/pdf",
            "markdown",
        )
        assert converter.opt_in is True
