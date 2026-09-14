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

from collections.abc import Mapping

from dossier.domain.scoring import FieldKind


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
    return kinds
