"""R7.18 — a judge verdict is cached under the judge model, the rubric hash, the
judge prompt hash, the document's text hash and the candidate answer, and the
judge is asked only on a miss.

R0.10's promise is that a model is asked only on a cache miss, and a judge is a
model. Its verdict is an artifact like any stage's: a content-addressed file with
a provenance record, in its own namespace. The judge here is a `FakeModelClient`
that **counts calls**, because three of the rows are claims about how many.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes import FakeModelClient

from dossier.domain.hashing import content_hash

JUDGE = "anthropic:claude-sonnet-4-5-20250929"
RUBRIC = "f7a2d9c4" * 8
PROMPT = "0e52dd18" * 8
DOCUMENT = "The renewed TLS certificate was never deployed to the load balancers."
RC_01 = (
    "The renewed TLS certificate was issued into Vault but never deployed to the "
    "load balancers, because deployment needed a Terraform apply that nobody ran; "
    "the expiry alert went to an archived Slack channel."
)
RC_02 = "The quarter-end change freeze caused the checkout outage."


def _inputs(*, candidate: str = RC_01, judge: str = JUDGE, document: str = DOCUMENT):
    from dossier.domain.keys import JudgeInputs

    return JudgeInputs(
        judge_model=judge,
        rubric_hash=RUBRIC,
        prompt_hash=PROMPT,
        document_hash=content_hash(document.encode("utf-8")),
        candidate_hash=content_hash(candidate.encode("utf-8")),
    )


class TestAJudgeVerdictIsCachedAndTheJudgeAskedOnAMiss:
    """R7.18 — the verdict is an artifact; the judge is a model asked on a miss."""

    def test_the_key_names_the_five_inputs_and_moves_with_any_of_them(self):
        """The key half of row 1: what a verdict is addressed by.

        Which judge, what it was asked (rubric and wrapper), what it was shown
        (the document's text) and what it was asked about (the candidate) --
        and nothing else. The gold set and the run id are not in it: a verdict
        on a candidate is the same whichever gold set it is scored against.
        """
        from dossier.domain.keys import cache_key, provenance

        key = cache_key(_inputs())

        assert cache_key(_inputs()) == key, "the same five inputs, the same key"
        assert cache_key(_inputs(candidate=RC_02)) != key
        assert cache_key(_inputs(judge="anthropic:claude-opus-4-1-20250805")) != key
        assert cache_key(_inputs(document=DOCUMENT + " Nobody noticed.")) != key
        record = provenance(_inputs(), run_id="20260806T142203Z-4f1a", dossier_version="0.1.0")
        assert {
            "judge_model",
            "rubric_hash",
            "prompt_hash",
            "document_hash",
            "candidate_hash",
        } <= record.keys()
        assert record["cache_key"] == key
