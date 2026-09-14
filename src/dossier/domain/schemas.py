"""The shape of an extracted field (spec 006).

These models are the shape of a record, not the list of fields. Which fields a
step extracts, and what kind each one is, is written once in the step's YAML
declaration; `dossier.domain.fields` combines the two into the schema shown to
the model (R6.10). Two definitions of one schema disagree eventually, and the
disagreement surfaces as a scoring bug months later.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Confidence = Literal["high", "medium", "low", "none"]


class Evidence(BaseModel):
    """Where a value came from: the document, the page, and the sentence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: str
    span: str
    page: int | None = None


class FieldRecord(BaseModel):
    """One extracted field, with its evidence or its reason for abstaining."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    value: float | int | str | bool | None = None
    currency: str | None = None
    reason: str | None = None
    confidence: Confidence | None = None
    source: Evidence | None = None


class StageOutput(BaseModel):
    """What one `per_file` stage returns for one document (spec 006).

    Its JSON schema, with `field` limited to the declared names, is what the
    model is shown; the answer is validated against the same model (R6.10).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: str
    fields: list[FieldRecord]
