"""R8.4 — one snapshot yields one artifact per declared conversion, each independently
addressed and keyed.

`OPS-114` is a PDF in `procedures-confluence`, declared `convert: [markdown,
page_images]`. `pdf-markdown` `1.3.0` and `pdf-images` `0.9.1` stand in for the
two converters spec 008's diagram names; each one's output depends on its
version, as a real converter's does.
"""

from __future__ import annotations

from pathlib import Path

from dossier.application.convert import ConvertReport, HeldDocument, convert_source
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.store import SnapshotStore

KINDS = ["markdown", "page_images"]
PDF = b"%PDF-1.4\nOPS-114: incident review procedure\n"


class PdfMarkdown:
    id = "pdf-markdown"
    media_type = "application/pdf"
    kind = "markdown"

    def __init__(self, version: str = "1.3.0") -> None:
        self.version = version

    def convert(self, payload: bytes, options) -> bytes:
        return f"# extracted by {self.version}\n".encode() + payload


class PdfImages:
    id = "pdf-images"
    media_type = "application/pdf"
    kind = "page_images"

    def __init__(self, version: str = "0.9.1") -> None:
        self.version = version

    def convert(self, payload: bytes, options) -> bytes:
        return f"PNG pages rendered by {self.version}\n".encode()


def convert(
    workspace: Path, documents: dict[str, bytes], *, images: str = "0.9.1", kinds=KINDS
) -> ConvertReport:
    store = SnapshotStore(workspace)
    return convert_source(
        source_id="procedures-confluence",
        documents={
            key: HeldDocument(snapshot=store.put(payload), media_type="application/pdf")
            for key, payload in documents.items()
        },
        kinds=kinds,
        converters=[PdfMarkdown(), PdfImages(images)],
        store=store,
        cache=ArtifactCache(workspace, namespace="convert"),
    )


def cached_artifacts(workspace: Path) -> list[Path]:
    """Converted artifacts in the cache, without the provenance record beside each."""
    return [
        path
        for path in (workspace / ".dossier" / "cache" / "convert").rglob("*")
        if path.is_file() and not path.name.endswith(".meta.json")
    ]


class TestEachDeclaredConversionIsItsOwnArtifact:
    """R8.4 — one artifact per declared conversion, each independently keyed."""

    def test_two_kinds_are_two_artifacts_under_two_keys(self, tmp_path: Path):
        """Example 1: the one where `OPS-114` declares `convert: [markdown, page_images]`.

        Two artifacts, two distinct convert keys, from one snapshot.
        """
        report = convert(tmp_path, {"OPS-114": PDF})

        (document,) = report.documents
        assert sorted(artifact.kind for artifact in document.artifacts) == KINDS
        assert len({artifact.key for artifact in document.artifacts}) == 2
        assert len(cached_artifacts(tmp_path)) == 2

    def test_raising_one_converter_reconverts_only_its_kind(self, tmp_path: Path):
        """Example 2: the one where `pdf-images` goes `0.9.1` -> `0.9.2`.

        The page-images artifact re-converts; the markdown artifact, whose
        converter did not move, is served from cache. Independently keyed means
        exactly this: one conversion's version is not in the other's key.
        """
        convert(tmp_path, {"OPS-114": PDF})

        raised = convert(tmp_path, {"OPS-114": PDF}, images="0.9.2")

        (document,) = raised.documents
        served = {artifact.kind: artifact.served_from_cache for artifact in document.artifacts}
        assert served == {"markdown": True, "page_images": False}

    def test_identical_bytes_share_one_artifact(self, tmp_path: Path):
        """Example 3: the one with two snapshots of byte-identical content.

        Same converter, same options: one artifact, as content addressing
        deduplicates snapshots (R0.2 example 3). The second document is a cache
        hit on the first one's key, not a second conversion.
        """
        report = convert(tmp_path, {"OPS-114": PDF, "OPS-115": PDF}, kinds=["markdown"])

        first, second = report.documents
        assert first.artifacts[0].key == second.artifacts[0].key
        assert (report.converted, report.cached) == (1, 1)
        assert len(cached_artifacts(tmp_path)) == 1

    def test_which_kind_a_stage_reads_is_not_decided_here(self, tmp_path: Path):
        """Counter-example (row 4): the one where a stage declares `input: documents`.

        Not resolved here: conversion produces every declared kind and takes no
        stage, step or pipeline to choose between them. Which kind a stage reads
        is a pipeline question (spec 003), not a conversion one.
        """
        report = convert(tmp_path, {"OPS-114": PDF})

        (document,) = report.documents
        assert {artifact.kind for artifact in document.artifacts} == set(KINDS)
        parameters = convert_source.__code__.co_varnames[
            : convert_source.__code__.co_kwonlyargcount
        ]
        assert not {"step", "stage", "pipeline", "input"} & set(parameters)
