"""Turning held snapshots into documents a stage can read (spec 008).

Two phases, and the split between them is the pair of rules this module exists
for. Every document's converter is resolved first; only then is anything
converted.

That order is what separates the two failures. A media type nobody claims means
the pipeline is not configured to read what it was pointed at -- nothing about
the run is well-defined, so nothing happens (R8.5). A converter that fails on one
document's bytes means the configuration is right and one input is bad -- so the
rest convert and the run says which one failed (R8.6).

They look alike and behave differently on purpose. Collapsing them one way turns
an installation problem into nine mysterious per-document errors; the other way
turns one corrupt PDF into a run that produced nothing.

Nothing here reaches the network: conversion is right of the hash boundary
(R0.1). Nothing here reads a clock either -- an artifact is a pure function of
the snapshot bytes and the declared options (R8.1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from dossier.domain.conversion import NoConverter, select
from dossier.domain.keys import ConvertInputs, cache_key, provenance
from dossier.domain.ports import ArtifactStore, Converter, SnapshotReader

# The kind whose artifact is text a stage can ground a span in (R6.4).
MARKDOWN = "markdown"


class HeldDocument(BaseModel):
    """One document as the ledger holds it: a snapshot, and what kind of bytes.

    `media_type` travels with the document rather than being inferred from its
    key, because a name on disk is not evidence about content (R8.3 example 4).
    """

    model_config = ConfigDict(frozen=True)

    snapshot: str
    media_type: str


@dataclass(frozen=True)
class Artifact:
    """One converted artifact, and whether producing it cost anything."""

    document: str
    kind: str
    converter_id: str
    converter_version: str
    key: str
    served_from_cache: bool


@dataclass(frozen=True)
class DocumentConversion:
    """What one document produced, or why it produced nothing."""

    document: str
    artifacts: tuple[Artifact, ...] = ()
    text: str | None = None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class ConvertReport:
    """What one source's conversion did, in the terms R8.8 reports (spec 008)."""

    source_id: str
    documents: tuple[DocumentConversion, ...] = ()

    @property
    def held(self) -> int:
        return len(self.documents)

    @property
    def converted(self) -> int:
        return sum(
            1
            for document in self.documents
            for artifact in document.artifacts
            if not artifact.served_from_cache
        )

    @property
    def cached(self) -> int:
        return sum(
            1
            for document in self.documents
            for artifact in document.artifacts
            if artifact.served_from_cache
        )

    @property
    def failed(self) -> tuple[DocumentConversion, ...]:
        """Every document that produced nothing, each with its own reason.

        A tuple rather than a count, and each carrying its own message: ten
        failures are ten pieces of evidence, and collapsing them into one summary
        hides which document failed how (R8.6 example 4).
        """
        return tuple(document for document in self.documents if document.failed)

    @property
    def text(self) -> dict[str, str]:
        """The converted text per document, for the stages that read it.

        Only the `markdown` kind: a stage grounds spans in text (R6.4), and page
        images are not text. A document that failed is absent rather than empty,
        so a stage cannot silently audit a blank page.
        """
        return {
            document.document: document.text
            for document in self.documents
            if document.text is not None
        }


def convert_inputs(
    *,
    snapshot: str,
    converter_id: str,
    converter_version: str,
    options: Mapping[str, str] | None = None,
) -> ConvertInputs:
    """Everything a conversion's key is composed of, composed one way.

    Used by a conversion when it is made and by a replay when it is read back
    (R4.7): two compositions of the same key is how a replay comes to miss an
    artifact the run wrote. A manifest pins no options (spec 004), so a replay
    composes with none -- which is what every run passes today.
    """
    return ConvertInputs(
        snapshot=snapshot,
        converter_id=converter_id,
        converter_version=converter_version,
        options=dict(options or {}),
    )


def convert_source(
    *,
    source_id: str,
    documents: Mapping[str, HeldDocument],
    kinds: Sequence[str] | None,
    converters: Sequence[Converter],
    store: SnapshotReader,
    cache: ArtifactStore,
    options: Mapping[str, str] | None = None,
    run_id: str = "",
    dossier_version: str = "",
) -> ConvertReport:
    """Convert every held document, or refuse the whole source (R8.5, R8.6)."""
    declared = dict(options or {})
    plan = _resolve_converters(documents=documents, kinds=kinds, converters=converters)

    conversions = tuple(
        _convert_one(
            document=key,
            held=documents[key],
            chosen=plan[key],
            store=store,
            cache=cache,
            options=declared,
            run_id=run_id,
            dossier_version=dossier_version,
        )
        for key in sorted(documents)
    )
    return ConvertReport(source_id=source_id, documents=conversions)


def _resolve_converters(
    *,
    documents: Mapping[str, HeldDocument],
    kinds: Sequence[str] | None,
    converters: Sequence[Converter],
) -> dict[str, list[Converter]]:
    """Which converters answer for each document, or refuse the source (R8.5).

    Every document is resolved before any is converted, and one unclaimed pair
    stops all of them. The alternative -- discovering it partway through -- would
    leave a source half converted for a reason that was knowable before any work
    started.

    Every unclaimed document is named, not just the first. Someone who pointed a
    pipeline at a folder of mixed files wants the list, not one example and
    another run.
    """
    plan: dict[str, list[Converter]] = {}
    unclaimed: list[str] = []

    for key in sorted(documents):
        try:
            plan[key] = select(
                media_type=documents[key].media_type, kinds=kinds, available=converters
            )
        except NoConverter as error:
            unclaimed.append(f"  {key} ({documents[key].media_type}): {error}")

    if unclaimed:
        raise NoConverter(
            f"{len(unclaimed)} document(s) have no converter:\n" + "\n".join(unclaimed)
        )

    return plan


def _convert_one(
    *,
    document: str,
    held: HeldDocument,
    chosen: Sequence[Converter],
    store: SnapshotReader,
    cache: ArtifactStore,
    options: Mapping[str, str],
    run_id: str,
    dossier_version: str,
) -> DocumentConversion:
    """One document, isolated from every other (R8.6).

    Any exception the converter raises belongs to this document alone. It is
    caught here rather than left to propagate, because a corrupt PDF is a
    statement about that PDF and not about the other nine.
    """
    artifacts: list[Artifact] = []
    text: str | None = None

    try:
        payload = store.get(held.snapshot)
        for converter in chosen:
            artifact, produced = _one_artifact(
                document=document,
                held=held,
                converter=converter,
                payload=payload,
                cache=cache,
                options=options,
                run_id=run_id,
                dossier_version=dossier_version,
            )
            artifacts.append(artifact)
            if converter.kind == MARKDOWN:
                # Decoded once, here, so a stage is handed text rather than
                # bytes it would have to guess an encoding for.
                text = produced.decode("utf-8")
    except Exception as error:  # noqa: BLE001 - a converter may raise anything
        return DocumentConversion(document=document, error=f"{type(error).__name__}: {error}")

    return DocumentConversion(document=document, artifacts=tuple(artifacts), text=text)


def _one_artifact(
    *,
    document: str,
    held: HeldDocument,
    converter: Converter,
    payload: bytes,
    cache: ArtifactStore,
    options: Mapping[str, str],
    run_id: str,
    dossier_version: str,
) -> tuple[Artifact, bytes]:
    """One (document, kind) artifact, converted or served from cache.

    The key is computed before the cache is consulted and before the converter is
    called, from the snapshot hash and this converter's identity and options
    (R5.4, R8.2). Nothing else can make an artifact differ, which is the promise
    the cache is trading on.
    """
    inputs = convert_inputs(
        snapshot=held.snapshot,
        converter_id=converter.id,
        converter_version=converter.version,
        options=options,
    )
    key = cache_key(inputs)

    stored = cache.get(key, require_record=True)
    if stored is None:
        stored = converter.convert(payload, options)
        # With its record, as a stage artifact is. It is the only diagnosis
        # available for the hazard `domain/ports.py` warns about and says no test
        # can enforce: an author who improves a converter without raising its
        # version, leaving a cache of artifacts claiming to be something they are
        # not (R0.3, R5.1).
        cache.put(
            key,
            stored,
            record=provenance(
                inputs, run_id=run_id, dossier_version=dossier_version, step="convert"
            ),
        )
        served = False
    else:
        served = True

    return (
        Artifact(
            document=document,
            kind=converter.kind,
            converter_id=converter.id,
            converter_version=converter.version,
            key=key,
            served_from_cache=served,
        ),
        stored,
    )
