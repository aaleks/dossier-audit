"""R7.21 — a `described` field is put to the judge with the document's pages.

R7.17 hands every deferred free-text field to the judge with the document's
converted text, and a document shown as pictures has none. Before this that was
a `KeyError` on a picture-only document -- the whole of `dossier eval` falling
over on exactly the evidence the visual slice exists to read.

Asserted against a fake that counts calls and records what each was shown,
because every row here is a claim about *which* call was made with *what*, and
none of them is a claim about what a judge answered.
"""

from __future__ import annotations

import json

import pytest

from dossier.application.eval import SHOWN_AS_PAGES, Judging, judge_scores
from dossier.application.extract import DocumentResult
from dossier.application.run import StepReport
from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.ports import ImagePart
from dossier.domain.schemas import FieldRecord
from dossier.domain.scoring import DocumentScore, FieldScore, Verdict

CHART = "INC-5720-checkout-latency-postmortem.png"
NOTE = "INC-4821"

CANDIDATE = "a retry storm exhausted the payments-api connection pool"
PAGE = ImagePart(media_type="image/png", data=b"\x89PNG\r\n\x1a\n one")
OTHER = ImagePart(media_type="image/png", data=b"\x89PNG\r\n\x1a\n two")

SUPPORTED = json.dumps({"supported": True, "evidence": "the Root cause section"})


class Cache:
    """An artifact store that keeps what it is given, and counts nothing else."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}

    def get(self, key: str, *, require_record: bool = False) -> bytes | None:
        return self.entries.get(key)

    def put(self, key: str, payload: bytes, *, record=None) -> None:
        self.entries[key] = payload

    def record(self, key: str):
        return None


def _record(document: str) -> FieldRecord:
    return FieldRecord.model_validate(
        {
            "field": "root_cause",
            "value": CANDIDATE,
            "source": {"document": document, "span": "a span"},
        }
    )


def _report(document: str, verdict: FieldVerdict) -> StepReport:
    return StepReport(
        step="extract",
        results=(
            DocumentResult(
                document=document,
                records=(_record(document),),
                checks=(FieldCheck(verdict, "why"),),
            ),
        ),
    )


def _score(document: str) -> DocumentScore:
    return DocumentScore(
        document=document,
        results=(FieldScore("root_cause", Verdict.NEEDS_JUDGE, "free text"),),
    )


def _judging(model, cache, *, documents, parts) -> Judging:
    return Judging(
        model=model,
        cache=cache,
        documents=documents,
        parts=parts,
        rubrics={"root_cause": ("is it supported?", "r" * 64)},
        judge_model="openai:gpt-5.4-mini",
        run_id="20260919T000000Z-0001",
        dossier_version="0.1.0",
    )


class TestADescribedFieldIsJudgedFromThePages:
    """R7.21 — the judge is shown what the stage was shown."""

    def test_the_judge_is_shown_the_page_and_told_there_is_no_transcript(self):
        """Example 1: the one the whole visual slice is evaluated through.

        Two assertions, and both matter: the page reached the judge as a part,
        and the body says the pages are what it has. A call carrying the image
        and an empty transcript would read as a document that says nothing.
        """
        from tests.fakes import FakeModelClient

        model = FakeModelClient(responses=[SUPPORTED])

        judge_scores(
            [_score(CHART)],
            report=_report(CHART, FieldVerdict.DESCRIBED),
            judging=_judging(model, Cache(), documents={}, parts={CHART: [PAGE]}),
        )

        assert model.call_count == 1
        assert model.calls[0]["parts"] == (PAGE,)
        assert SHOWN_AS_PAGES in str(model.calls[0]["prompt"])

    def test_a_grounded_field_is_judged_from_the_text_as_before(self):
        """Example 2: the one where nothing about the text judge moves.

        The same field, the same candidate, a grounded record. No parts, and
        the document's own text in the prompt (R7.17).
        """
        from tests.fakes import FakeModelClient

        model = FakeModelClient(responses=[SUPPORTED])
        text = "The pool was exhausted by a retry storm after the failover."

        judge_scores(
            [_score(NOTE)],
            report=_report(NOTE, FieldVerdict.VALID),
            judging=_judging(model, Cache(), documents={NOTE: text}, parts={}),
        )

        assert model.calls[0]["parts"] == ()
        assert text in str(model.calls[0]["prompt"])
        assert SHOWN_AS_PAGES not in str(model.calls[0]["prompt"])

    def test_the_same_described_candidate_is_asked_once(self):
        """Example 3: the verdict is cached under the pages (R7.18).

        Zero calls the second time is the assertion. A judge is a model, and
        R0.10 says a model is reached only on a cache miss -- which a verdict
        keyed on evidence nobody hashed would silently stop being true of.
        """
        from tests.fakes import FakeModelClient

        cache = Cache()
        first = FakeModelClient(responses=[SUPPORTED])
        judge_scores(
            [_score(CHART)],
            report=_report(CHART, FieldVerdict.DESCRIBED),
            judging=_judging(first, cache, documents={}, parts={CHART: [PAGE]}),
        )

        second = FakeModelClient(responses=[])
        judge_scores(
            [_score(CHART)],
            report=_report(CHART, FieldVerdict.DESCRIBED),
            judging=_judging(second, cache, documents={}, parts={CHART: [PAGE]}),
        )

        assert first.call_count == 1
        assert second.call_count == 0

    def test_different_pages_are_a_different_verdict(self):
        """Example 4: the pages are the evidence, so they are in the key.

        Same candidate, same document name, a different picture. A key that
        ignored the images would serve the first verdict for the second page
        and never ask -- which is the failure a cache key exists to prevent.
        """
        from tests.fakes import FakeModelClient

        cache = Cache()
        for page in (PAGE, OTHER):
            model = FakeModelClient(responses=[SUPPORTED])
            judge_scores(
                [_score(CHART)],
                report=_report(CHART, FieldVerdict.DESCRIBED),
                judging=_judging(model, cache, documents={}, parts={CHART: [page]}),
            )
            assert model.call_count == 1, "a different picture served an old verdict"

        assert len(cache.entries) == 2

    def test_a_described_field_with_no_pages_is_left_unscored(self):
        """Counter-example 5: the one where there is nothing honest to ask.

        A workspace that no longer holds the pages cannot be judged against
        them, and judging against an empty prompt would produce a verdict about
        nothing. The field stays deferred, which is what `scored` already
        excludes -- and no call is made.
        """
        from tests.fakes import FakeModelClient

        model = FakeModelClient(responses=[])

        scored = judge_scores(
            [_score(CHART)],
            report=_report(CHART, FieldVerdict.DESCRIBED),
            judging=_judging(model, Cache(), documents={}, parts={}),
        )

        assert model.call_count == 0
        assert scored[0].results[0].verdict is Verdict.NEEDS_JUDGE
        assert scored[0].scored == (), "a field nobody could judge was counted"

    def test_a_described_field_never_reaches_the_text_map(self):
        """The regression this rule was found by: a KeyError on eval.

        `judging.documents` has no entry for a picture-only document, and the
        old path indexed it unconditionally. Asserting no exception is the
        point; the verdict is incidental.
        """
        from tests.fakes import FakeModelClient

        with pytest.raises(KeyError):
            {}[CHART]

        judge_scores(
            [_score(CHART)],
            report=_report(CHART, FieldVerdict.DESCRIBED),
            judging=_judging(
                FakeModelClient(responses=[SUPPORTED]),
                Cache(),
                documents={},
                parts={CHART: [PAGE]},
            ),
        )
