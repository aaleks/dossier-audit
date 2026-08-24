"""The shape of an extracted field (spec 006).

One pydantic model generates the schema shown to the model, the validation
applied to its answer, and the field list a scorer works from. There is no second
definition anywhere -- two definitions of one schema disagree eventually, and the
disagreement surfaces as a scoring bug months later (R6.7).
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
