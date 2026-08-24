"""Running one stage over one document (spec 006).

Ask the model, validate the answer against the declared schema, retry once if it
does not conform, and check every field against the documents the stage actually
read. A document that fails after the retry is reported and skipped; the run
continues (R6.9).

Takes the model client as an argument and constructs none, which is what lets the
whole path run against `FakeModelClient` and lets the tests assert *how many*
calls happened rather than only what came back.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from dossier.domain.grounding import FieldCheck, check_field
from dossier.domain.ports import ModelClient
from dossier.domain.schemas import FieldRecord, StageOutput

# One retry, and exactly one. A model that cannot produce the shape twice will
# not produce it on the fifth attempt either, and an unbounded retry loop turns a
# bad prompt into a bill (R6.2).
MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class DocumentResult:
    """What one document's pass through a stage produced."""

    document: str
    records: tuple[FieldRecord, ...] = ()
    checks: tuple[FieldCheck, ...] = ()
    attempts: int = 0
    error: str | None = None

    @property
    def failed(self) -> bool:
        """Whether this document produced no usable output at all.

        A document with ungrounded or invalid *fields* has not failed -- it has
        findings, and they go to review (spec 007). Failure here means the stage
        could not get a well-formed answer for the document at all, and so there
        is nothing to write and nothing to cache (R6.1).
        """
        return self.error is not None

    @property
    def field_failures(self) -> tuple[FieldCheck, ...]:
        return tuple(check for check in self.checks if check.is_failure)


def run_stage(
    *,
    document: str,
    prompt: str,
    schema: dict,
    model: ModelClient,
    input_documents: Mapping[str, str],
) -> DocumentResult:
    """Run one stage for one document, validating and grounding the answer."""
    attempts = 0
    correction: str | None = None

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        response = model.complete(_with_correction(prompt, correction), schema=schema)

        try:
            output = StageOutput.model_validate_json(response)
        except (ValidationError, ValueError) as error:
            correction = str(error)
            continue

        checks = tuple(
            check_field(record, input_documents=input_documents) for record in output.fields
        )
        return DocumentResult(
            document=document,
            records=tuple(output.fields),
            checks=checks,
            attempts=attempts,
        )

    # Second failure. The document is reported as failed and is not cached; the
    # run continues for every other document (R6.1, R6.9).
    return DocumentResult(
        document=document,
        attempts=attempts,
        error=f"{document}: no valid output after {attempts} attempts -- {correction}",
    )


def _with_correction(prompt: str, correction: str | None) -> str:
    """The retry carries the validation error, so the model can see what it broke.

    Retrying with the identical prompt would be asking the same question again
    and hoping -- which is not a retry strategy, it is a coin flip with a bill
    attached (R6.2).
    """
    if correction is None:
        return prompt
    return (
        f"{prompt}\n\n"
        "<validation_error>\n"
        "Your previous answer did not validate against the required schema. "
        f"Correct it and return only the corrected answer.\n{correction}\n"
        "</validation_error>\n"
    )
