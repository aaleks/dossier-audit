"""A photocopied PDF in, text out, through Docling (spec 008, R8.14, R8.15).

`pdf-markdown` reads a PDF's text layer, and a photocopy has none: the artifact
is its anchors and nothing else, and no field in it can ever be grounded. This
converter runs Docling over the document instead -- a page with a text layer read
from it, a page with none read by OCR -- and is opt-in, because it claims the pair
`pdf-markdown` claims and a workspace chooses it by name (R8.13).

**Its models are part of it.** Docling reads a layout model and a table model
from Hugging Face, and by default downloads them the first time it needs them, at
revision `main`. That is the network on the path every artifact is made on
(R0.10), and a floating name deciding what an artifact says. Here the weights are
read from Docling's model folder at the commits pinned below, and every file read
is checked against the SHA-256 recorded for its commit before a page is converted
(R8.15). Where the folder is differs between machines; which bytes it holds does
not, so its location cannot reach an artifact (R8.1).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

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
