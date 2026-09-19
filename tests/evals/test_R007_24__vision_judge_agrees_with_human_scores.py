"""R7.24 — the vision judge agrees with human scores on the visual sample.

R7.11 for the other judge. The same question -- is this candidate supported by
this document -- asked of a document supplied as pictures, and the figure is
what the `described` bar in `judge.yaml` was set from.

A real model call per case, each carrying every page of its document as a PNG,
so this is `live` and never part of the default suite. It gates: `a.aleks`
agreed 0.90 on 2026-09-19, over this sample and after seeing what it measured.

Run it, with an OpenWebUI endpoint reachable:

    uv run python -m pytest tests/evals -m live -s

The documents are rendered by the shipped converters rather than read from a
generator, so this measures the same bytes a run would show a judge (R8.11,
R8.12).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.application.eval import SHOWN_AS_PAGES, judge_prompt_hash, judged
from dossier.config.endpoints import endpoint_for
from dossier.config.environment import environment
from dossier.domain.conversion import PART_TYPE, unpack_parts
from dossier.domain.hashing import text_hash
from dossier.domain.judges import (
    MINIMUM_SAMPLE,
    Calibration,
    NotCalibrated,
    agreement,
    calibration,
    is_eligible,
)
from dossier.domain.model_id import provider_of
from dossier.domain.ports import ImagePart
from dossier.infrastructure.converters.image_pages import PngPagesConverter
from dossier.infrastructure.converters.pdf_images import PdfImagesConverter
from dossier.infrastructure.models.registry import provider as model_provider

pytestmark = pytest.mark.live

# Agreed by `a.aleks` on 2026-09-19, over this sample (R7.24). The bound is
# inclusive. Set below the 21 of 22 measured twice: at N=22 that supports a 95%
# lower bound near 0.78, and a gate at the measured figure has no room for the
# next borderline case anyone adds. A judge calling everything supported scores
# 13 of 22 = 59.1% here, which is the floor this has to clear to mean anything.
#
# Below the text judge's 0.95 on purpose. Reading the page and then judging it
# is the harder job, and the one case it misses says so: on INC-5455 it reads a
# hypothesis table's `Verdict` column as an assertion, in a document whose every
# page header says ROOT CAUSE NOT ESTABLISHED.
THRESHOLD = 0.90

JUDGE_MODEL = "openai:gpt-5.4-mini"

REPOSITORY = Path(__file__).resolve().parents[2]
CASES = REPOSITORY / "tests" / "evals" / "golden" / "root_cause_visual.jsonl"
RUBRIC = (
    REPOSITORY / "tests" / "fixtures" / "pipelines" / "incident-audit" / "rubrics"
) / "root_cause.md"


def cases() -> list[dict]:
    """The human-scored visual sample, as the reviewer left it."""
    return [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pages(case: dict) -> list[ImagePart]:
    """The document as the judge will see it: one picture per page.

    Rendered by the shipped converter, so this measures the bytes a run would
    produce rather than a rendering written for the test (R8.11, R8.12).
    """
    path = REPOSITORY / case["path"]
    payload = path.read_bytes()
    converter = PdfImagesConverter() if path.suffix.lower() == ".pdf" else PngPagesConverter()
    return [
        ImagePart(media_type=PART_TYPE, data=part)
        for part in unpack_parts(converter.convert(payload, {}))
    ]


def judge():
    """The judge, built the way a run builds a model client (R9.1, R9.2).

    `environment(...)` rather than `os.environ`, so `.env` is read (R9.11) --
    the same reasoning, and the same past mistake, as R7.11's.
    """
    name = provider_of(JUDGE_MODEL)
    factory = model_provider(name)
    endpoint = endpoint_for(
        name,
        default_url=getattr(factory, "default_url", None),
        environ=environment(REPOSITORY),
    )
    return factory(JUDGE_MODEL, url=endpoint.url, api_key=endpoint.api_key)


@pytest.fixture(scope="module")
def measured() -> dict:
    """Every case put to the judge once, as pages, with the evidence it gave."""
    rubric = RUBRIC.read_text(encoding="utf-8")
    model = judge()

    verdicts: dict[str, bool] = {}
    evidence: dict[str, str] = {}
    shown: dict[str, int] = {}
    for case in cases():
        parts = pages(case)
        shown[case["id"]] = len(parts)
        supported, why = judged(
            model,
            rubric=rubric,
            document=case["document"],
            # The body `dossier eval` asks with, unchanged (R7.21). A prompt
            # tuned here would measure the tuning, and the bar would then be
            # set from it (R7.11).
            text=SHOWN_AS_PAGES,
            answer=case["answer"],
            parts=parts,
        )
        verdicts[case["id"]] = supported
        evidence[case["id"]] = why

    human = {case["id"]: case["supported"] for case in cases()}
    figure, disagreed = agreement(verdicts=verdicts, human=human)
    return {
        "verdicts": verdicts,
        "evidence": evidence,
        "human": human,
        "pages": shown,
        "agreement": figure,
        "disagreed": disagreed,
        "calibration": calibration(
            verdicts=verdicts,
            human=human,
            judge_model=JUDGE_MODEL,
            rubric_hash=text_hash(RUBRIC),
            prompt_hash=judge_prompt_hash(),
        ),
    }


class TestVisionJudgeAgreesWithHumanScores:
    """R7.24 — measured against the reviewer, shown pictures."""

    def test_the_judge_agrees_at_the_agreed_threshold(self, measured: dict):
        """Example 1: the one the `described` bar is set from."""
        assert measured["agreement"] >= THRESHOLD

        print(f"\n  judge:      {JUDGE_MODEL}")
        print(f"  sample:     {len(measured['human'])} human-scored visual cases")
        print(f"  pages sent: {sum(measured['pages'].values())}")
        print(f"  agreement:  {measured['agreement']:.1%}")
        print(f"  disagreed:  {', '.join(measured['disagreed']) or 'none'}")
        for case in measured["disagreed"]:
            print(
                f"    {case}: human={measured['human'][case]} "
                f"judge={measured['verdicts'][case]} — {measured['evidence'][case][:160]}"
            )

    def test_the_sample_is_large_enough_to_mean_anything(self, measured: dict):
        """Example 1's precondition. Below twenty there is nothing to gate."""
        assert len(measured["human"]) >= MINIMUM_SAMPLE

    def test_the_figure_carries_the_judge_and_the_sample_size(self, measured: dict):
        """Example 2: a figure without its judge says a judge agreed with a human."""
        recorded: Calibration = measured["calibration"]

        assert recorded.judge_model == JUDGE_MODEL
        assert recorded.sample_size == len(measured["human"])
        assert recorded.rubric_hash and len(recorded.rubric_hash) == 64

    def test_the_threshold_clears_the_always_supported_floor(self, measured: dict):
        """Example 3: the one that says the bar measures something.

        A judge answering "supported" to every case scores the share of the
        sample that is supported. A threshold at or below that measures
        nothing at all, however respectable it looks.
        """
        floor = sum(measured["human"].values()) / len(measured["human"])

        assert floor < THRESHOLD, (
            f"a judge calling everything supported would score {floor:.1%}, "
            f"which clears the agreed {THRESHOLD}"
        )

    def test_a_smaller_sample_is_refused_rather_than_reported(self, measured: dict):
        """R7.11 row 3, which this sample is subject to as any other is."""
        thin = measured["calibration"].model_copy(update={"sample_size": 5})

        with pytest.raises(NotCalibrated):
            is_eligible(thin, threshold=THRESHOLD)

    def test_the_cases_carried_from_the_text_sample_say_where_they_came_from(self):
        """Counter-example 4: the two samples are not interchangeable.

        Twenty cases are the same proposition about the same document, differing
        only in what the judge is shown, and each says so. The two on `INC-5720`
        are not carried and could not be: it has no text layer, so the text
        judge cannot be asked about it at all.
        """
        rows = cases()
        carried = [row for row in rows if row.get("carried_from")]
        native = [row for row in rows if not row.get("carried_from")]

        assert len(carried) == 20
        assert all(row["shown_as"] == "page_images" for row in rows)
        assert {row["document"] for row in native} == {
            "INC-5720-checkout-latency-postmortem.png"
        }
