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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from dossier.domain.grounding import FieldCheck, check_field, with_derived_page
from dossier.domain.ports import ImagePart, ModelClient, Tracker
from dossier.domain.schemas import FieldRecord, StageOutput
from dossier.domain.tracking import span_payload

# One retry, and exactly one. A model that cannot produce the shape twice will
# not produce it on the fifth attempt either, and an unbounded retry loop turns a
# bad prompt into a bill (R6.2).
MAX_ATTEMPTS = 2

# What the retry tells the model. Model-facing text, so a change here changes what
# is asked on every retry -- named rather than built inline so that shows up in a
# diff rather than staying buried in a function body.
#
# Not in any cache key: a stage key covers the prompt template, not the rendered
# prompt (spec 005), so editing this invalidates nothing. That is correct, and it
# is also why it needs to be visible -- nothing else would notice it moved.
CORRECTION_TEMPLATE = (
    "<validation_error>\n"
    "Your previous answer did not validate against the required schema. "
    "Correct it and return only the corrected answer.\n"
    "{error}\n"
    "</validation_error>\n"
)


@dataclass(frozen=True)
class DocumentResult:
    """What one document's pass through a stage produced."""

    document: str
    records: tuple[FieldRecord, ...] = ()
    checks: tuple[FieldCheck, ...] = ()
    attempts: int = 0
    error: str | None = None
    # The artifact this result *is*, verbatim, where that is not derivable from
    # `records`. Two cases: a step with no output schema, which spec 003 allows an
    # `aggregate` step to be (R3.5 example 4) and whose answer is prose; and a
    # cache hit, which carries the stored bytes forward rather than re-deriving
    # them.
    text: str | None = None

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
    schema: dict | None,
    model: ModelClient,
    input_documents: Mapping[str, str],
    parts: Sequence[ImagePart] = (),
    tracker: Tracker | None = None,
    capture: str = "full",
    hashes: Mapping[str, object] | None = None,
) -> DocumentResult:
    """Run one stage for one document, validating and grounding the answer.

    `schema=None` means the step declared no output, which spec 003 permits an
    `aggregate` step to do. There is then nothing to validate against and nothing
    to retry for, so the first answer is the answer -- and R6.2's one retry stays
    exactly what it is, a response to a *validation* failure.
    """
    if schema is None:
        text = _asked(
            tracker,
            model,
            prompt,
            schema=None,
            attempt=1,
            capture=capture,
            hashes=hashes,
            parts=parts,
        )
        _llm_span(
            tracker,
            model,
            attempt=1,
            error=None,
            prompt=prompt,
            reply=text,
            capture=capture,
            hashes=hashes,
        )
        return DocumentResult(document=document, attempts=1, text=text)

    attempts = 0
    correction: str | None = None

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        asked = _with_correction(prompt, correction)
        response = _asked(
            tracker,
            model,
            asked,
            schema=schema,
            attempt=attempts,
            capture=capture,
            hashes=hashes,
            parts=parts,
        )

        try:
            output = StageOutput.model_validate_json(response)
        except (ValidationError, ValueError) as error:
            correction = str(error)
            _llm_span(
                tracker,
                model,
                attempt=attempts,
                error=correction,
                prompt=asked,
                reply=response,
                capture=capture,
                hashes=hashes,
            )
            continue

        _llm_span(
            tracker,
            model,
            attempt=attempts,
            error=None,
            prompt=asked,
            reply=response,
            capture=capture,
            hashes=hashes,
        )
        # The page is read off the document before anything records it (R6.14).
        # Done here rather than inside check_field because it is a different
        # question: check_field says whether the evidence holds, this says where
        # it is. Both search the same normalised text, so they cannot disagree.
        records = tuple(
            with_derived_page(record, input_documents=input_documents)
            for record in output.fields
        )
        checks = tuple(
            check_field(record, input_documents=input_documents) for record in records
        )
        return DocumentResult(
            document=document,
            records=records,
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


def _asked(
    tracker: Tracker | None,
    model: ModelClient,
    prompt: str,
    *,
    schema: dict | None,
    attempt: int,
    capture: str,
    hashes: Mapping[str, object] | None,
    parts: Sequence[ImagePart] = (),
) -> str:
    """One model call. A call that raised is still one call, so still one LLM span.

    The span says why it failed in the error's own words -- a refusal by URL
    and status, never by key, because the error itself never holds one (R9.8
    row 1, R10.7 row 2). Then the error travels on: recording a failure is not
    handling it.
    """
    try:
        return model.complete(prompt, schema=schema, parts=parts)
    except Exception as error:
        _llm_span(
            tracker,
            model,
            attempt=attempt,
            error=str(error),
            prompt=prompt,
            reply="",
            capture=capture,
            hashes=hashes,
        )
        raise


def _llm_span(
    tracker: Tracker | None,
    model: ModelClient,
    *,
    attempt: int,
    error: str | None,
    prompt: str,
    reply: str,
    capture: str,
    hashes: Mapping[str, object] | None,
) -> None:
    """One model call, one LLM span (R11.2).

    The span and the model's call count are the same claim seen twice (R5.5). A
    span whose answer failed validation carries the error it was retried on, so
    a retry is explained where it happened rather than only counted (R6.2).

    What else it holds is `capture`'s decision (R10.8): the prompt as sent and
    the reply as received under `full`, or the prompt template's hash, the
    input hashes and the key under `hashes` -- which say exactly what was
    asked without holding a word of it. `hashes` is `None` only for a call no
    key describes, and `full` never needs it.
    """
    if tracker is None:
        return
    identity: dict[str, object] = {
        "dossier.model": model.model_id,
        "dossier.attempt": attempt,
    }
    if error is not None:
        identity["error"] = error
    attributes = span_payload(
        capture=capture,
        identity=identity,
        prompt=prompt,
        reply=reply,
        hashes=hashes or {"prompt": "", "inputs": (), "key": ""},
    )
    tracker.span(kind="llm", name=model.model_id, attributes=attributes)


def _with_correction(prompt: str, correction: str | None) -> str:
    """The retry carries the validation error, so the model can see what it broke.

    Retrying with the identical prompt would be asking the same question again
    and hoping -- which is not a retry strategy, it is a coin flip with a bill
    attached (R6.2).
    """
    if correction is None:
        return prompt
    return f"{prompt}\n\n" + CORRECTION_TEMPLATE.format(error=correction)
