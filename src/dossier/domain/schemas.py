"""The shape of an extracted field (spec 006).

These models are the shape of a record, not the list of fields. Which fields a
step extracts, and what kind each one is, is written once in the step's YAML
declaration; `dossier.domain.fields` combines the two into the schema shown to
the model (R6.10). Two definitions of one schema disagree eventually, and the
disagreement surfaces as a scoring bug months later.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

Confidence = Literal["high", "medium", "low", "none"]


def failure_reason(error: Exception, *, attempts: int) -> str:
    """Why an answer was refused, as the line reporting its document says it (R6.32).

    Each error pydantic found, as `location: message`, or the message alone
    where the whole answer is at fault, joined by `; `: every one of them,
    since a count would hide the rest wherever MLflow is off. Not pydantic's
    own text, which opens with a header, quotes the reply and ends with a
    link. Nor the document's name, which the line already gives. A refusal the
    run makes itself, such as a field answered twice (R6.24), is its own words.
    Each on one line, because the line reporting it is one (R6.31).

    The retry prompt and each attempt's span keep pydantic's full text (R6.2,
    R11.2): this is what a person reads, not what the model is shown.
    """
    if isinstance(error, ValidationError):
        said = [
            _located(detail) for detail in error.errors(include_url=False, include_input=False)
        ]
    else:
        said = [str(error)]
    return f"no valid output after {attempts} attempts: " + "; ".join(
        " ".join(text.split()) for text in said
    )


def _located(detail: Any) -> str:
    location = ".".join(str(part) for part in detail["loc"])
    return f"{location}: {detail['msg']}" if location else detail["msg"]


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
