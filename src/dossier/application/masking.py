"""Masking a pipeline's documents before any model is shown them (spec 021).

Each document's converted text becomes its masked view: cached under `K_mask`
(R21.5), with a provenance record naming its inputs, its language and how many
values of each type it masked -- never a value. A document whose masking
fails, or whose key names a client, is failed by name and left out: it is
never sent unmasked instead (R21.8).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from dossier.domain.keys import cache_key, mask_inputs, provenance
from dossier.domain.masking import (
    MaskerUnavailable,
    Masking,
    language_of,
    mask,
    mask_with_mapping,
    readable_key,
)
from dossier.domain.ports import ArtifactStore, Masker

# The cache namespace masked views are kept in. `gc` does not collect it, as it
# does not collect the judge cache: a masked view is small text, and a kept run
# replayed after a `gc` must find it (spec 021, "The masked view").
MASK = "mask"
# Where each masked view's mapping is kept, under the view's key (R21.21):
# placeholder to value. Local, read by calibrate and eval (R21.20, R21.23),
# and never collected by `gc`, as the views are not.
MASK_VALUES = "mask-values"


@dataclass(frozen=True)
class MaskedTexts:
    """The masked view of each document that could be masked, and why each other could not."""

    texts: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)
    # Each masked document's mapping, placeholder to value (R21.21): what a
    # gold value or a candidate about it is masked with (R21.22). Local only.
    mappings: dict[str, dict[str, str]] = field(default_factory=dict)
    # How many values of each type each masked view holds: its record's, never
    # a value (R21.25).
    counts: dict[str, dict[str, int]] = field(default_factory=dict)


def mask_texts(
    texts: Mapping[str, str],
    *,
    masking: Masking,
    masker: Masker,
    cache: ArtifactStore,
    run_id: str,
    dossier_version: str,
    values: ArtifactStore | None = None,
) -> MaskedTexts:
    """Every document in `texts`, by key, masked; a failure fails that one alone (R21.8).

    `values` keeps each view's mapping under the view's key (R21.21). Without
    it, the mappings are still returned, and kept nowhere.
    """
    shown: dict[str, str] = {}
    failed: dict[str, str] = {}
    mappings: dict[str, dict[str, str]] = {}
    counts: dict[str, dict[str, int]] = {}
    view = _Viewer(
        masking, masker, cache, values=values, run_id=run_id, dossier_version=dossier_version
    )
    for key in sorted(texts):
        try:
            # A key is shown to the model in every `<document key="...">`
            # (R3.13), so a file named after a client carries the name past
            # its own masked text. Masked like any text, and cached like it.
            readable = readable_key(key)
            if view(readable)[0] != readable:
                failed[key] = (
                    "its key names client data, and a key is shown to the model; "
                    "rename it at the source"
                )
                continue
            shown[key], mappings[key], counts[key] = view(texts[key])
        except MaskerUnavailable:
            # Not this document's failure: the masker cannot run at all here,
            # and every document would fail alike. The run stops (R21.10).
            raise
        except Exception as error:  # noqa: BLE001 -- any failure of a masker fails closed
            # A masker is a library over statistical models: what it raises is
            # not ours to enumerate. Whatever it is, the document is not sent.
            failed[key] = f"masking failed: {error}"
    return MaskedTexts(texts=shown, failed=failed, mappings=mappings, counts=counts)


class _Viewer:
    """One text's masked view: from the cache under `K_mask`, or masked and kept."""

    def __init__(
        self,
        masking: Masking,
        masker: Masker,
        cache: ArtifactStore,
        *,
        values: ArtifactStore | None,
        run_id: str,
        dossier_version: str,
    ) -> None:
        self.masking = masking
        self.masker = masker
        self.cache = cache
        self.values = values
        self.run_id = run_id
        self.dossier_version = dossier_version

    def __call__(self, text: str) -> tuple[str, dict[str, str], dict[str, int]]:
        """The masked view of `text`, its mapping, and how many of each type it masked."""
        inputs = mask_inputs(
            text=text,
            masker_id=self.masker.id,
            masker_version=self.masker.version,
            declaration=self.masking.declaration_hash,
        )
        key = cache_key(inputs)
        held = self.cache.get(key, require_record=True)
        kept = None if self.values is None else self.values.get(key)
        if held is not None and (kept is not None or self.values is None):
            counted = (self.cache.record(key) or {}).get("masked", {})
            return held.decode("utf-8"), json.loads(kept or b"{}"), dict(counted)
        # A miss, or a view cached before its mapping was kept: masked again.
        # The masker's output is a function of the text (R21.13), so the view
        # rewritten here is the one already cached.
        language = language_of(text, self.masking.declaration.languages)
        found = self.masker.detect(text, language=language)
        masked, mapping, counts = mask_with_mapping(text, found, self.masking)
        if held is None:
            record = provenance(
                inputs, run_id=self.run_id, dossier_version=self.dossier_version
            )
            record["language"] = language
            record["masked"] = counts
            self.cache.put(key, masked.encode("utf-8"), record=record)
        if self.values is not None:
            # The values, beside the view and never in its record: a record
            # names no value (R21.21).
            self.values.put(
                key,
                json.dumps(mapping, sort_keys=True, ensure_ascii=False).encode("utf-8"),
                record={"kind": "mask-values", "cache_key": key},
            )
        return masked, mapping, counts


def mask_query(query: str, *, masking: Masking, masker: Masker) -> str:
    """A search's query as a masked index is searched with (R21.19).

    Masked before it is embedded, searched, printed or recorded: a name typed
    into a query would otherwise reach the embedding model, the vector cache's
    key and MLflow, and the masked query matches the placeholders the index
    holds. Not cached: a query is not a document, and is asked once.
    A masker that cannot run raises `MaskerUnavailable`; the search stops.
    """
    language = language_of(query, masking.declaration.languages)
    masked, _ = mask(query, masker.detect(query, language=language), masking)
    return masked
