"""The embedding index: what it is declared as, and what it carries (spec 018).

Everything here is a decision about the index, made from what was read: the
declaration, a pipeline's field kinds. Nothing here opens a file or reaches
the index. The index itself is derived data, rebuilt from the workspace
(R18.4), so every decision about what goes into it lives here, where it can
be proved without a database.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from dossier.domain.scoring import FieldKind


class ChunkerSettings(BaseModel):
    """Which chunker cuts the documents, and with what (R18.1, R18.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    max_chars: int = Field(gt=0)


class IndexFields(BaseModel):
    """The fields of the pipeline's output the index carries (R18.9, R18.10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Exact values to filter on: a category is exact, and a vector would only
    # blur it.
    filter: tuple[str, ...] = ()
    # Free text, embedded in the document's record chunk.
    embed: tuple[str, ...] = ()


class IndexTarget(BaseModel):
    """Where the index is written. The connection string is a secret, so only
    the name of the variable holding it is written down (R1.8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dsn_env: str


class IndexDeclaration(BaseModel):
    """`indexes/<name>.yaml`: one index over one pipeline (spec 018)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # From the file's name, as a pipeline's is from its directory's.
    name: str
    pipeline: str
    embedding_model: str
    chunker: ChunkerSettings
    fields: IndexFields = IndexFields()
    target: IndexTarget


def field_refusals(
    fields: IndexFields, kinds: Mapping[str, FieldKind], *, declared_in: str
) -> list[tuple[str, str]]:
    """Each field the index may not carry, as `(group, why)`, in the order written (R18.10).

    A filter is an exact value and an embedded field is free text: the two are
    searched in different ways, and a field in the wrong group is searched in
    the wrong one. A field the output does not declare is a column the run never
    fills, found only by someone wondering why a filter returns nothing.
    """
    refused: list[tuple[str, str]] = []
    declared = ", ".join(sorted(kinds))
    for group, names in (("filter", fields.filter), ("embed", fields.embed)):
        for name in names:
            kind = kinds.get(name)
            if kind is None:
                why = (
                    f"fields.{group} names {name!r}, which {declared_in} does not "
                    f"declare. It declares: {declared}"
                )
            elif group == "filter" and kind is FieldKind.FREE_TEXT:
                why = (
                    f"fields.filter names {name!r}, a free_text field: free text is "
                    "embedded, not filtered"
                )
            elif group == "embed" and kind is not FieldKind.FREE_TEXT:
                why = (
                    f"fields.embed names {name!r}, {_article(kind.value)} {kind.value} "
                    "field: a category is filtered, not embedded"
                )
            else:
                continue
            refused.append((group, why))
    return refused


def _article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"
