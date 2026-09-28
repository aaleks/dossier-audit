"""R7.49 — a judged field is put to the judge once for each page that gave it a
value, and is correct only when the judge supports every one.

The judge is asked about the run's answer (R7.17), and a document read page by
page gives one answer per page. Before this rule the judge was asked about the
last page's record alone -- an abstention, as often as not -- and its verdict
was given to every page. The candidates are `_fixtures.md`'s `rc-01`,
supported, and `rc-02`, the planted claim.

Asserted against a fake judge that counts calls and records what each was
shown: every row is a claim about which calls were made with what.
"""

from __future__ import annotations

import json
from datetime import date

from dossier.application.eval import SHOWN_AS_PAGES, Judging, judge_scores, score_run
from dossier.application.extract import DocumentResult
from dossier.application.run import StepReport
from dossier.domain.gold import GoldDocument
from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.ports import ImagePart
from dossier.domain.schemas import FieldRecord
from dossier.domain.scoring import FieldKind, Verdict

POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
CAUSE = "the renewed TLS certificate was never deployed to the load balancers"
RC_01 = (
    "The renewed TLS certificate was issued into Vault but never deployed to the load "
    "balancers, because deployment needed a Terraform apply that nobody ran; the expiry "
    "alert went to an archived Slack channel."
)
RC_02 = "The quarter-end change freeze caused the checkout outage."
TEXT = "Service was restored by installing the renewed certificate, never deployed."

NAMES = ("page-001.png", "page-002.png", "page-003.png")
PAGES = tuple(ImagePart(media_type="image/png", data=f"page {n}".encode()) for n in (1, 2, 3))

DESCRIBED = FieldCheck(FieldVerdict.DESCRIBED, "shown as a picture")
GROUNDED = FieldCheck(FieldVerdict.VALID)
INVALID = FieldCheck(FieldVerdict.INVALID, "cites INC-4821, which the call was not shown")

SUPPORTED = json.dumps({"supported": True, "evidence": "the Root cause section"})
UNSUPPORTED = json.dumps({"supported": False, "evidence": "no change freeze caused it"})


class Cache:
    """An artifact store that keeps what it is given."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}

    def get(self, key: str, *, require_record: bool = False) -> bytes | None:
        return self.entries.get(key)

    def put(self, key: str, payload: bytes, *, record=None) -> None:
        self.entries[key] = payload

    def record(self, key: str):
        return None


def said(value: str) -> FieldRecord:
    return FieldRecord.model_validate(
        {"field": "root_cause", "value": value, "source": {"document": POSTMORTEM, "span": "x"}}
    )


def silent() -> FieldRecord:
    return FieldRecord(field="root_cause", value=None, reason="not on this page")


def judged(pages, judge, *, parts: bool = True):
    """`pages` is `(record, check)` for each page in part order; the field's verdict."""
    result = DocumentResult(
        document=POSTMORTEM,
        records=tuple(record for record, _ in pages),
        checks=tuple(check for _, check in pages),
        parts=NAMES[: len(pages)] if parts else (),
    )
    report = StepReport(step="extract", results=(result,))
    gold = GoldDocument(
        document=POSTMORTEM,
        verified_by="a.aleks",
        verified_at=date(2026, 9, 28),
        fields={"root_cause": {"value": CAUSE}},
    )
    scores = score_run(
        report=report, gold={POSTMORTEM: gold}, kinds={"root_cause": FieldKind.FREE_TEXT}
    )
    (score,) = judge_scores(
        scores,
        report=report,
        judging=Judging(
            model=judge,
            cache=Cache(),
            documents={POSTMORTEM: TEXT},
            parts={POSTMORTEM: PAGES},
            rubrics={"root_cause": ("is it supported?", "r" * 64)},
            judge_model="openai:gpt-5.4-mini",
            run_id="20260928T000000Z-0001",
            dossier_version="0.1.0",
        ),
    )
    (verdict,) = score.results
    return verdict


class TestEachPagesJudgedValueMustBeSupported:
    """R7.49 — every page's answer is judged, and every one must stand."""

    def test_the_one_page_that_answered_is_judged_from_the_pages(self):
        """Row 1 — the one where page 2 states the cause and pages 1 and 3 do not."""
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[SUPPORTED])

        verdict = judged(
            [(silent(), DESCRIBED), (said(RC_01), DESCRIBED), (silent(), DESCRIBED)], judge
        )

        assert judge.call_count == 1
        assert RC_01 in str(judge.calls[0]["prompt"]), (
            "the abstention was judged, not the answer"
        )
        assert judge.calls[0]["parts"] == PAGES
        assert verdict.verdict is Verdict.CORRECT

    def test_a_planted_claim_on_one_page_fails_the_field(self):
        """Row 2 — the one where page 3 is right and page 2 repeats the planted claim."""
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[UNSUPPORTED, SUPPORTED])

        verdict = judged(
            [(silent(), DESCRIBED), (said(RC_02), DESCRIBED), (said(RC_01), DESCRIBED)], judge
        )

        assert judge.call_count == 2
        assert RC_02 in str(judge.calls[0]["prompt"])
        assert RC_01 in str(judge.calls[1]["prompt"])
        assert verdict.verdict is Verdict.INCORRECT
        assert verdict.detail == "page-002.png: no change freeze caused it"

    def test_the_same_answer_on_two_pages_is_asked_once(self):
        """Row 3 — the one where one candidate on one evidence is one key (R7.18)."""
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[SUPPORTED])

        verdict = judged(
            [(silent(), DESCRIBED), (said(RC_01), DESCRIBED), (said(RC_01), DESCRIBED)], judge
        )

        assert judge.call_count == 1
        assert verdict.verdict is Verdict.CORRECT

    def test_a_page_read_as_text_and_a_page_read_as_a_picture_are_judged_apart(self):
        """Row 4 — the one where the same words on different evidence are two keys."""
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[SUPPORTED, SUPPORTED])

        judged([(said(RC_01), GROUNDED), (said(RC_01), DESCRIBED)], judge)

        assert judge.call_count == 2
        assert judge.calls[0]["parts"] == ()
        assert TEXT in str(judge.calls[0]["prompt"])
        assert judge.calls[1]["parts"] == PAGES
        assert SHOWN_AS_PAGES in str(judge.calls[1]["prompt"])

    def test_a_page_that_fails_without_a_judge_asks_no_judge(self):
        """Row 5 — the one where nothing the judge says could make the field correct."""
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[])

        verdict = judged(
            [(silent(), DESCRIBED), (said(RC_01), DESCRIBED), (said(RC_01), INVALID)], judge
        )

        assert judge.call_count == 0
        assert verdict.verdict is Verdict.INCORRECT

    def test_a_per_file_field_is_one_value_and_one_call(self):
        """Row 6, counter-example — the one R7.17 has always asked."""
        from tests.fakes import FakeModelClient

        judge = FakeModelClient(responses=[SUPPORTED])

        verdict = judged([(said(RC_01), GROUNDED)], judge, parts=False)

        assert judge.call_count == 1
        assert verdict.verdict is Verdict.CORRECT
