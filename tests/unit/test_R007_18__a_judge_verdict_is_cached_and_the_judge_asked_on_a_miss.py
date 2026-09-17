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

    def test_a_first_verdict_asks_the_judge_and_writes_the_artifact(self, tmp_path: Path):
        """Example 1: the one where nothing is cached.

        One call, and a verdict on disk under the judge namespace with its
        provenance record (R0.3): a content-addressed file like any stage's.
        """
        from dossier.application.eval import judged_cached
        from dossier.domain.keys import cache_key
        from dossier.infrastructure.cache import ArtifactCache

        cache = ArtifactCache(tmp_path, namespace="judge")
        judge = FakeModelClient(responses=[json.dumps({"supported": True, "evidence": "e"})])

        supported, evidence = judged_cached(
            judge,
            cache,
            inputs=_inputs(),
            rubric="Is the stated root cause supported by the named document?",
            document="INC-4830",
            text=DOCUMENT,
            answer=RC_01,
            run_id="20260806T142203Z-4f1a",
            dossier_version="0.1.0",
        )

        assert judge.call_count == 1
        assert (supported, evidence) == (True, "e")
        assert cache.get(cache_key(_inputs()), require_record=True) is not None
        assert list((tmp_path / ".dossier" / "cache" / "judge").rglob("*.meta.json"))

    def test_the_same_candidate_again_asks_nothing(self, tmp_path: Path):
        """Example 2: the one served from cache.

        Zero calls, and the same verdict byte for byte (R5.5): a judge that
        fails on any call is what proves the second eval asked nothing.
        """
        from tests.fakes import NoModelClient

        from dossier.application.eval import judged_cached
        from dossier.infrastructure.cache import ArtifactCache

        cache = ArtifactCache(tmp_path, namespace="judge")
        ask = dict(
            inputs=_inputs(),
            rubric="Is the stated root cause supported by the named document?",
            document="INC-4830",
            text=DOCUMENT,
            answer=RC_01,
            run_id="20260806T142203Z-4f1a",
            dossier_version="0.1.0",
        )
        judge = FakeModelClient(responses=[json.dumps({"supported": False, "evidence": "x"})])
        first = judged_cached(judge, cache, **ask)

        second = judged_cached(NoModelClient(), cache, **ask)

        assert second == first == (False, "x")

    def test_a_different_candidate_asks_about_that_candidate_only(self, tmp_path: Path):
        """Example 4: the one where a run changed one document's answer.

        The old candidate's verdict is still served; only the new candidate is
        asked about (R5.7's shape).
        """
        from dossier.application.eval import judged_cached
        from dossier.infrastructure.cache import ArtifactCache

        cache = ArtifactCache(tmp_path, namespace="judge")
        judge = FakeModelClient(
            responses=[
                json.dumps({"supported": True, "evidence": "a"}),
                json.dumps({"supported": False, "evidence": "b"}),
            ]
        )
        common = dict(
            rubric="Is the stated root cause supported by the named document?",
            document="INC-4830",
            text=DOCUMENT,
            run_id="20260806T142203Z-4f1a",
            dossier_version="0.1.0",
        )
        judged_cached(judge, cache, inputs=_inputs(), answer=RC_01, **common)

        judged_cached(judge, cache, inputs=_inputs(candidate=RC_02), answer=RC_02, **common)
        judged_cached(judge, cache, inputs=_inputs(), answer=RC_01, **common)

        assert judge.call_count == 2, "two candidates, two calls; the repeat is served"
