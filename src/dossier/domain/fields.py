"""The fields a step extracts, as its YAML declaration states them (spec 006).

A step's `output` names one declaration listing each field and what kind of
answer it holds. It is the only place a field's name and kind are written; the
JSON Schema shown to the model and the field list a scorer works from are both
derived from it, so neither can disagree with it or with the other (R6.10).

This module takes the declaration already parsed. Reading YAML is `config/`'s
job -- the domain imports no parser -- and taking a mapping is what lets every
decision here be tested without a file.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from dossier.domain.hashing import content_hash
from dossier.domain.schemas import StageOutput
from dossier.domain.scoring import FieldKind

# What a kind cannot be scored without. An enum with no vocabulary can match
# nothing, so every answer to it would score incorrect -- confidently, months
# from now (R6.10 example 4). Free text is scored by a judge against a written
# rubric, and there is no default rubric to fall back on: without one it could
# only be string-compared, which is the defect this refuses (R6.10 example 5).
_REQUIRES = {FieldKind.ENUM: "values", FieldKind.FREE_TEXT: "judge"}


@dataclass(frozen=True)
class OutputSchema:
    """What one declaration contributes to a run: the schema shown, and the hash keyed.

    Held together so the two cannot come from different declarations. The schema
    is generated from the declaration (R6.10); the hash is of the declaration's
    own text, so an edit the generated schema cannot see -- a rubric path, a
    comment -- still moves every key that depends on it (R6.11).
    """

    schema: dict
    declaration_hash: str

    @property
    def generated_schema_hash(self) -> str:
        """The hash of what the model is shown, over canonical JSON (R6.12).

        Sorted keys, fixed separators, UTF-8: the same schema gives the same
        bytes on every machine however its dict happened to be built (R5.6).
        Derived rather than stored, so it cannot disagree with the schema it
        describes.
        """
        return content_hash(
            json.dumps(
                self.schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        )


def json_schema(kinds: Mapping[str, FieldKind]) -> dict:
    """The JSON Schema shown to the model, generated from a declaration.

    The record's shape comes from `StageOutput`, the model the answer is
    validated against, and the names a record may carry come from the
    declaration. Neither is written a second time, so a field declared once is
    a field the model is asked for (R6.10 example 1).
    """
    schema = StageOutput.model_json_schema()
    schema["$defs"]["FieldRecord"]["properties"]["field"] = {
        "title": "Field",
        "enum": list(kinds),
    }
    return schema


def declare_fields(
    document: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> dict[str, FieldKind]:
    """The kind of every declared field, in declared order.

    This is the scorer's field list, in the shape `score_document` takes: derived
    from the declaration, never written anywhere else (R6.10 example 2). Raises
    `ValueError` naming what is wrong.
    """
    kinds: dict[str, FieldKind] = {}
    for name, declared in document["fields"].items():
        kind = declared["kind"]
        try:
            kinds[name] = FieldKind(kind)
        except ValueError:
            # The kind picks the scorer (spec 007), so a kind outside the five is
            # a field nobody decided how to score. Naming the five turns the
            # error into its own fix (R3.10 row 4).
            known = ", ".join(member.value for member in FieldKind)
            raise ValueError(
                f"field {name!r} declares kind {kind!r}, which is not one of: {known}"
            ) from None
        required = _REQUIRES.get(kinds[name])
        if required is not None and not declared.get(required):
            raise ValueError(
                f"field {name!r} is {kinds[name].value} with no `{required}`, "
                "and cannot be scored without one"
            )
    return kinds
