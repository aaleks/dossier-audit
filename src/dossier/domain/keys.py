"""Cache keys and the provenance records that explain them (spec 005).

One structure produces both. That is R5.1, and it is the whole design: a record
naming an input the key ignores means a change to that input silently serves a
stale artifact, and a key covering an input the record omits produces a miss
nobody can explain. Neither shows up as an error, so neither can be left to
convention.

The composition is spec 005's, verbatim:

    K_convert = H( snapshot_content_hash + converter_id + converter_version + options )
    K_stage   = H( prompt_hash + schema_hash + generated_schema_hash + model_id
                   + stage_options + sorted(input_artifact_hashes) )

Everything entering a key is a hash, an identifier or a declared option. No
paths, no clock, no absolute anything -- R5.6 is the claim that a key is the same
on every machine, and the cheapest way to hold it is to give the key nothing that
could vary.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from dossier.domain.hashing import content_hash

# Recorded so an artifact can be traced, and excluded from the key because
# neither may change an output (R0.4, R5.1 example 4). `step` joins them because
# spec 005's K_stage does not contain it: two steps with identical prompt,
# schema, model, options and inputs are the same computation and correctly share
# a cache entry. The id is in the record so a reader still knows who wrote it.
PROVENANCE_ONLY = frozenset({"step", "run_id", "dossier_version", "cache_key"})


class ArtifactInput(BaseModel):
    """One thing a computation read: what it was for, where it is, what it was.

    `hash` enters the key. `role` and `path` are for the person reading the
    record -- a hash alone answers "did this change?" and nothing else.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    path: str
    hash: str


class ConvertInputs(BaseModel):
    """Everything `K_convert` is composed of, and nothing else (R5.4, R8.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot: str
    converter_id: str
    converter_version: str
    options: dict[str, str] = {}

    def keyed(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot,
            "converter_id": self.converter_id,
            "converter_version": self.converter_version,
            "options": self.options,
        }

    def recorded(self) -> dict[str, Any]:
        return self.keyed()


class StageInputs(BaseModel):
    """Everything `K_stage` is composed of, plus the step id it is recorded under.

    `extra="forbid"` is the mechanism behind R5.1 example 3. Adding a field to
    this model is how a record and a key drift apart, so a field nobody thought
    about is refused at construction rather than discovered as a cache that
    stopped invalidating.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: str
    prompt: ArtifactInput
    # Not `schema`: that name shadows a BaseModel attribute. The record still
    # writes it as `schema`, because that is what spec 005's example shows.
    output_schema: ArtifactInput | None = None
    # The hash of the JSON Schema the model is shown, beside the declaration's.
    # A change to dossier's own generator changes what the model is asked with no
    # byte of the declaration moving, and R0.5 says that must move a key (R6.12).
    generated_schema: str | None = None
    model: str
    options: dict[str, str] = {}
    inputs: list[ArtifactInput] = []

    def keyed(self) -> dict[str, Any]:
        """The key's inputs, in a canonical form.

        Input hashes are sorted. Two inputs supplied in a different order are the
        same inputs, and relying on the order they arrived in is the bug that
        makes a cache hit on the machine that wrote it and miss everywhere else
        (R5.6 example 4).
        """
        return {
            "prompt": self.prompt.hash,
            "schema": self.output_schema.hash if self.output_schema else None,
            "generated_schema": self.generated_schema,
            "model": self.model,
            "options": self.options,
            "inputs": sorted(artifact.hash for artifact in self.inputs),
        }

    def recorded(self) -> dict[str, Any]:
        """The same inputs, with the paths and roles a person needs to read them."""
        return {
            "prompt": self.prompt.model_dump(),
            "schema": self.output_schema.model_dump() if self.output_schema else None,
            "generated_schema": (
                {"hash": self.generated_schema} if self.generated_schema else None
            ),
            "model": self.model,
            "options": self.options,
            "inputs": [artifact.model_dump() for artifact in self.inputs],
        }


def canonical(inputs: ConvertInputs | StageInputs) -> bytes:
    """The exact bytes a key is taken over.

    `sort_keys` and a fixed separator rather than whatever `json` feels like:
    the whole point is that two processes agree, and a default that changed
    between Python versions would silently split a cache in two (R5.6).
    """
    return json.dumps(
        inputs.keyed(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def cache_key(inputs: ConvertInputs | StageInputs) -> str:
    """The full 64-character lowercase SHA-256 of the canonical form (R0.7)."""
    return content_hash(canonical(inputs))


def provenance(
    inputs: ConvertInputs | StageInputs,
    *,
    run_id: str,
    dossier_version: str,
    step: str | None = None,
) -> dict[str, Any]:
    """The sibling `<name>.meta.json` for one artifact (R0.3, R5.1).

    Built from the same object the key is, so the two describe the same inputs by
    construction. The only fields here that are not in the key are the ones
    `PROVENANCE_ONLY` names, and each of them is there because a person needs it
    and no output depends on it.
    """
    record = dict(inputs.recorded())
    record["cache_key"] = cache_key(inputs)
    record["run_id"] = run_id
    record["dossier_version"] = dossier_version
    record["step"] = step if step is not None else getattr(inputs, "step", None)
    return record
