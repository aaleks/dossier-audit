"""R11.15 — the judge's LLM span carries what a stage span carries.

A stage's span holds the rendered prompt and the model's reply under `full`, and
their hashes under `hashes` (R10.8). A judge's span held its model identifier and
nothing else, so the one question in `dossier` whose answer is a *judgement* was
the one call nobody could read back: the verdict and the evidence were in the
cache artifact, on the scoring machine and not on the server.

The same payload, under the same setting, for the same reason.
"""

from __future__ import annotations

from dossier.application.eval import judge_span
from dossier.domain.keys import JudgeInputs

DOCUMENT = "INC-4830"
FIELD = "root_cause"
CANDIDATE = "the renewed TLS certificate was never deployed to the load balancers"
PROMPT = f"Is this candidate supported by document {DOCUMENT}? <claim>{CANDIDATE}</claim>"
REPLY = '{"supported": true, "evidence": "the certificate paragraph"}'
MODEL = "anthropic:claude-sonnet-4-5-20250929"
KEY = "9f21c0a4"

INPUTS = JudgeInputs(
    judge_model=MODEL,
    rubric_hash="f7a2d9c4",
    prompt_hash="0e52dd18",
    document_hash="5d3ba0f7",
    candidate_hash="77c1b40a",
)


def _span(capture: str) -> dict[str, object]:
    return judge_span(
        capture=capture,
        inputs=INPUTS,
        field=FIELD,
        document=DOCUMENT,
        prompt=PROMPT,
        reply=REPLY,
        key=KEY,
    )


class TestAJudgeSpanCarriesWhatAStageSpanCarries:
    """R11.15 — the judge's LLM span carries what a stage span carries."""

    def test_full_capture_holds_the_question_and_the_reply(self):
        """Example 1: the one where a person wants to see what the judge was asked.

        As R10.8 row 1 gives a stage. Before this, the question existed in no
        record at all -- only in a cache entry on the machine that scored.
        """
        carried = _span("full")

        assert carried["prompt"] == PROMPT
        assert carried["reply"] == REPLY

    def test_hashes_capture_holds_no_words_of_the_document_or_the_candidate(self):
        """Example 2: the one where the document may not reach the server.

        A judge's question embeds the whole document *and* the candidate answer,
        so `hashes` has more to withhold here than anywhere else. The assertion
        is that neither appears, not that some field was renamed.
        """
        carried = _span("hashes")
        written = " ".join(str(value) for value in carried.values())

        assert PROMPT not in written
        assert CANDIDATE not in written
        assert REPLY not in written
        assert INPUTS.document_hash in written, "the hashes are what replace them"
        assert KEY in written

    def test_both_settings_identify_the_field_the_document_and_the_judge(self):
        """Example 3: the one R10.8 row 4 already settled for a stage.

        They identify; they do not disclose. Without them a span under `hashes`
        would be a set of hashes with no way to tell which verdict it was.
        """
        for capture in ("full", "hashes"):
            carried = _span(capture)

            assert carried["dossier.field"] == FIELD
            assert carried["dossier.document"] == DOCUMENT
            assert carried["dossier.model"] == MODEL
