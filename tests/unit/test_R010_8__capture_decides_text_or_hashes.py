"""R10.8 — `DOSSIER_MLFLOW_CAPTURE` decides whether a span carries document text or
only its hashes.

A span that holds the rendered prompt and the model's reply is the most useful
record there is -- and it copies document text into a server that may be shared
more widely than the documents are. `hashes` keeps every span identifiable and
comparable without holding a word of the text: the prompt, input and key hashes
say exactly what was asked, and anyone holding the documents can check them.

Pure: the setting arrives from the environment as a mapping, and the payload is
decided before the tracker port sees it. The hashes are `_fixtures.md`'s,
written in full as a real one is (R0.7).
"""

from __future__ import annotations

import pytest

from dossier.domain.tracking import capture, span_payload

PROMPT = "Verify the extracted fields against the document.\n<document>...</document>\n"
REPLY = '{"document": "INC-4821", "fields": []}'
HASHES = {
    "prompt": "0e52dd18" * 8,
    "inputs": ["a3f9c1e2" * 8, "77c1b40a" * 8],
    "key": "9f21c0a4" * 8,
}
# What identifies the span. It says which work this was, and discloses nothing.
IDENTITY = {
    "dossier.step": "verify",
    "dossier.document": "INC-4821",
    "dossier.model": "anthropic:claude-sonnet-4-5-20250929",
    "dossier.attempts": 1,
    "dossier.fields": ["loss_amount", "resolution_date"],
    "dossier.verdicts": {"loss_amount": "valid", "resolution_date": "valid"},
}


def _verify_span(environ):
    return span_payload(
        capture=capture(environ), identity=IDENTITY, prompt=PROMPT, reply=REPLY, hashes=HASHES
    )


class TestCaptureDecidesTextOrHashes:
    """R10.8 — full text or only hashes, as the machine's setting says."""

    def test_unset_captures_the_prompt_and_the_reply(self):
        """Example 1: the one where nothing is set, so `full` applies."""
        span = _verify_span({})

        assert span["prompt"] == PROMPT
        assert span["reply"] == REPLY

    def test_hashes_captures_the_hashes_and_no_text(self):
        """Example 2: the one with `DOSSIER_MLFLOW_CAPTURE=hashes`.

        The span still says exactly what was asked -- prompt `0e52dd18`, inputs
        `a3f9c1e2` and `77c1b40a`, key `9f21c0a4` -- and holds none of it.
        """
        span = _verify_span({"DOSSIER_MLFLOW_CAPTURE": "hashes"})

        assert span["prompt_hash"] == "0e52dd18" * 8
        assert span["input_hashes"] == ["a3f9c1e2" * 8, "77c1b40a" * 8]
        assert span["key"] == "9f21c0a4" * 8
        assert PROMPT not in span.values()
        assert REPLY not in span.values()
        assert "prompt" not in span and "reply" not in span

    def test_any_other_value_is_refused_naming_the_two_it_takes(self):
        """Example 3: the one with `DOSSIER_MLFLOW_CAPTURE=none`.

        Refused before any work: reading it as `full` would copy text the person
        meant to keep out, and reading it as `hashes` would guess.
        """
        with pytest.raises(ValueError) as error:
            capture({"DOSSIER_MLFLOW_CAPTURE": "none"})

        message = str(error.value)
        assert "DOSSIER_MLFLOW_CAPTURE" in message
        assert "full" in message and "hashes" in message

    def test_what_identifies_a_span_is_recorded_under_both_values(self):
        """Counter-example (row 4): the step, document, model, attempts, fields and verdicts.

        Recorded either way. They say which work the span was, and disclose
        nothing a person would want kept out.
        """
        for environ in ({}, {"DOSSIER_MLFLOW_CAPTURE": "hashes"}):
            span = _verify_span(environ)
            assert {name: span[name] for name in IDENTITY} == IDENTITY
