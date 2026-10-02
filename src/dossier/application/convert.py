"""Turning held snapshots into documents a stage can read (spec 008).

Two phases, and the split between them is the pair of rules this module exists
for. Every document's converter is resolved first; only then is anything
converted.

That order is what separates the two failures. A kind a source declared that
nothing claims means the pipeline is not configured to read what it was pointed
at -- nothing about the run is well-defined, so nothing happens (R8.24). A
converter that fails on one document's bytes means the configuration is right
and one input is bad -- so the rest convert and the run says which one failed
(R8.6). A default kind nothing claims is the second kind: nobody asked for that
file to be read, so it is that document that is reported (R8.25).

They look alike and behave differently on purpose. Collapsing them one way turns
an installation problem into nine mysterious per-document errors; the other way
turns one corrupt PDF into a run that produced nothing.

Nothing here reaches the network: conversion is right of the hash boundary
(R0.19). Nothing here reads a clock either -- an artifact is a pure function of
the snapshot bytes and the declared options (R8.1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from dossier.domain.conversion import (
    Convert,
    NoConverter,
    UnclaimedDefault,
    claims,
    kinds_for,
    select,
)
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
    content: Mapping[str, bytes] = field(default_factory=dict)
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def text(self) -> str | None:
        """The `markdown` artifact as text, or `None` if this document has none.

        Kept as a named property because it is what every step reading bare
        `documents` gets (R3.11), and because a stage is handed text rather than
        bytes it would have to guess an encoding for.
        """
        produced = self.content.get(MARKDOWN)
        return None if produced is None else produced.decode("utf-8")


@dataclass(frozen=True)
class ConvertReport:
    """What one source's conversion did, in the terms R8.8 reports (spec 008)."""

    source_id: str
    documents: tuple[DocumentConversion, ...] = ()
    # The documents whose media type the source maps to no kinds, in key order
    # (R8.27). Held, and read by nothing: not a failure, and not present.
    left_out: tuple[str, ...] = ()

    @property
    def held(self) -> int:
        return len(self.documents) + len(self.left_out)

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

    def content(self, kind: str) -> dict[str, bytes]:
        """Every document's artifact of `kind`, for the steps that read it.

        A document that failed, or that this source never produced this kind
        for, is absent rather than empty -- so a stage cannot silently audit a
        blank page (R6.13's shape).
        """
        return {
            document.document: document.content[kind]
            for document in self.documents
            if kind in document.content
        }

    @property
    def present(self) -> tuple[str, ...]:
        """Every document this conversion produced something for, in key order.

        Not `text`. A source declaring `convert: [page_images]` produces no
        markdown at all, and building the run's document set from the text map
        made such a document invisible: it converted, it was cached, and then no
        step ran for it and the run reported zero documents with nothing failed
        (R6.15). What makes a document part of a run is that it converted, not
        which kind it converted to.
        """
        return tuple(
            sorted(document.document for document in self.documents if not document.failed)
        )

    @property
    def text(self) -> dict[str, str]:
        """The converted text per document, for the stages reading bare `documents`.

        The `markdown` kind: a stage grounds spans in text (R6.4). Another kind
        is reached through `content`, which is what R3.11 gave a step the words
        to ask for.
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
    kinds: Convert,
    converters: Sequence[Converter],
    store: SnapshotReader,
    cache: ArtifactStore,
    options: Mapping[str, str] | None = None,
    run_id: str = "",
    dossier_version: str = "",
) -> ConvertReport:
    """Convert every held document, or refuse the whole source (R8.6, R8.24, R8.25)."""
    declared = dict(options or {})
    plan, unread = _resolve_converters(documents=documents, kinds=kinds, converters=converters)
    # A media type the source maps to `[]` is read by nothing (R8.27). Its
    # documents are counted, and kept out of every conversion and every step.
    left_out = tuple(
        key for key in sorted(documents) if kinds_for(kinds, documents[key].media_type) == []
    )

    conversions = tuple(
        DocumentConversion(document=key, error=unread[key])
        if key in unread
        else _convert_one(
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
        if key not in left_out
    )
    return ConvertReport(source_id=source_id, documents=conversions, left_out=left_out)


def refuse_unconvertible(
    sources: Sequence[tuple[Mapping[str, HeldDocument], Convert]],
    *,
    converters: Sequence[Converter],
) -> None:
    """Refuse the run before anything converts, in any source (R8.24).

    `convert_source` refuses its own source before converting it. A command
    converts source by source, so checked there alone, a declared pair nothing
    claims in the second source was refused after the first had written its
    artifacts -- and nothing said so. Every source is resolved here first, and
    every unclaimed document of every source is named in one refusal.
    """
    claims(converters)
    unclaimed = [
        line
        for documents, kinds in sources
        for line in _resolve(documents=documents, kinds=kinds, converters=converters)[2]
    ]
    if unclaimed:
        raise NoConverter(_refusal(unclaimed))


def _resolve_converters(
    *,
    documents: Mapping[str, HeldDocument],
    kinds: Convert,
    converters: Sequence[Converter],
) -> tuple[dict[str, list[Converter]], dict[str, str]]:
    """Which converters answer for each document, or refuse the source (R8.24).

    Every document is resolved before any is converted, and one declared pair
    nothing claims stops all of them. The alternative -- discovering it partway
    through -- would leave a source half converted for a reason that was
    knowable before any work started. Across sources, `refuse_unconvertible`
    makes the same promise.

    Every unclaimed document is named, not just the first. Someone who pointed a
    pipeline at a folder of mixed files wants the list, not one example and
    another run.

    A default pair nothing claims is set aside with its reason instead: nobody
    asked for that file to be read, so it fails alone and the rest convert
    (R8.25).
    """
    # Two converters claiming one pair is an installation to settle, whatever
    # any document is and whoever chose its kind: refused once, as that, and
    # not as every document of the source having no converter (R8.24 row 5).
    claims(converters)
    plan, unread, unclaimed = _resolve(documents=documents, kinds=kinds, converters=converters)
    if unclaimed:
        raise NoConverter(_refusal(unclaimed))
    return plan, unread


def _resolve(
    *,
    documents: Mapping[str, HeldDocument],
    kinds: Convert,
    converters: Sequence[Converter],
) -> tuple[dict[str, list[Converter]], dict[str, str], list[str]]:
    """Each document's converters, the defaulted ones nothing reads, and the refused."""
    plan: dict[str, list[Converter]] = {}
    unread: dict[str, str] = {}
    unclaimed: list[str] = []

    for key in sorted(documents):
        try:
            plan[key] = select(
                media_type=documents[key].media_type, kinds=kinds, available=converters
            )
        except UnclaimedDefault as error:
            unread[key] = str(error)
        except NoConverter as error:
            unclaimed.append(f"  {key} ({documents[key].media_type}): {error}")

    return plan, unread, unclaimed


def _refusal(unclaimed: Sequence[str]) -> str:
    """Every unclaimed document, of however many sources, in one refusal (R8.24)."""
    return f"{len(unclaimed)} document(s) have no converter:\n" + "\n".join(unclaimed)


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
    content: dict[str, bytes] = {}

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
            # Every kind, not only `markdown`. Keeping one of them was what made
            # `page_images` an artifact no step could name (R3.11): it was
            # counted, keyed and invalidated, and then dropped on the floor.
            content[converter.kind] = produced
    except Exception as error:  # noqa: BLE001 - a converter may raise anything
        return DocumentConversion(document=document, error=f"{type(error).__name__}: {error}")

    return DocumentConversion(document=document, artifacts=tuple(artifacts), content=content)


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
