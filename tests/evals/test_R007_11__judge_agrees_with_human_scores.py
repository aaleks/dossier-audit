"""R7.11 — the free-text judge agrees with human scores on the calibration sample.

A real model call per case, so this is `live` and never part of the default
suite. It measures; it does not yet gate. R7.11's threshold is still `OPEN`, and
the spec is explicit about why: the figure belongs to the domain expert who signs
off the gold set, and one invented here would become a test, become a gate, and
be discovered to be arbitrary three features later.

So `THRESHOLD` below is `None`, and row 1 is reported rather than asserted. The
rest of the rule is asserted today: the sample is large enough to mean anything,
the figure carries the judge model and the size of the sample it came from, a
smaller sample is refused rather than reported as a percentage, and the
deterministic fields stay out of the measurement.

Run it, with an Ollama or OpenWebUI endpoint reachable:

    uv run python -m pytest tests/evals -m live -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from dossier.application.eval import agreement, calibration, judged
from dossier.config.endpoints import endpoint_for
from dossier.config.environment import environment
from dossier.domain.hashing import text_hash
from dossier.domain.judges import MINIMUM_SAMPLE, Calibration, NotCalibrated, is_eligible
from dossier.domain.model_id import provider_of
from dossier.infrastructure.models.registry import provider as model_provider

pytestmark = pytest.mark.live

# The number the domain expert has yet to agree. Until it is a number, R7.11
# stays NOT MET and this file reports the measurement instead of gating on it.
THRESHOLD: float | None = None

# A stable OpenAI code, which is a pin (R9.14), reached through the local
# OpenWebUI that DOSSIER_OPENAI_URL names (R9.2, R9.7).
#
# It replaces a local Ollama model, and the reason is worth recording: this
# machine has around 4GB free, and three attempts at the sample were killed for
# memory before a single case was recorded. A judge that cannot finish twenty
# cases cannot calibrate anything, and the endpoint costs no local RAM at all.
JUDGE_MODEL = "openai:gpt-5.4-mini"

REPOSITORY = Path(__file__).resolve().parents[2]
CASES = REPOSITORY / "tests" / "evals" / "golden" / "root_cause.jsonl"
RUBRIC = REPOSITORY / "tests" / "fixtures" / "pipelines" / "incident-audit" / "rubrics"


def cases() -> list[dict]:
    """The human-scored calibration sample, as the reviewer left it."""
    return [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def document_text(case: dict) -> str:
    """The document a case was scored against, as text.

    Read from the committed PDF rather than from the generator that wrote it:
    the reviewer scored what the document says, and the PDF is what a run would
    convert and hand to a judge.
    """
    reader = PdfReader(REPOSITORY / case["path"])
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def judge():
    """The judge, built the way a run builds a model client (R9.1, R9.2).

    The provider is read off the identifier rather than named here, so pointing
    the measurement at another model is one constant and not three -- which is
    the whole point of `model:` naming what answers and the environment naming
    where it is served.
    """
    name = provider_of(JUDGE_MODEL)
    factory = model_provider(name)
    # `endpoint_for` reads the mapping it is handed and nothing else. The CLI
    # hands it `environment(...)`, which is the shell with `.env` beneath it
    # (R9.11); reading `os.environ` directly here would skip `.env` and reach
    # OpenAI's public API with no key, which is exactly what it did.
    endpoint = endpoint_for(
        name,
        default_url=getattr(factory, "default_url", None),
        environ=environment(REPOSITORY),
    )
    return factory(JUDGE_MODEL, url=endpoint.url, api_key=endpoint.api_key)


@pytest.fixture(scope="module")
def measured() -> dict:
    """Every case put to the judge once, with the verdicts and the evidence it gave."""
    rubric_path = RUBRIC / "root_cause.md"
    rubric = rubric_path.read_text(encoding="utf-8")
    model = judge()

    verdicts: dict[str, bool] = {}
    evidence: dict[str, str] = {}
    for case in cases():
        supported, why = judged(
            model,
            rubric=rubric,
            document=case["document"],
            text=document_text(case),
            answer=case["answer"],
        )
        verdicts[case["id"]] = supported
        evidence[case["id"]] = why

    human = {case["id"]: case["supported"] for case in cases()}
    figure, disagreed = agreement(verdicts=verdicts, human=human)
    return {
        "verdicts": verdicts,
        "evidence": evidence,
        "human": human,
        "agreement": figure,
        "disagreed": disagreed,
        "calibration": calibration(
            verdicts=verdicts,
            human=human,
            judge_model=JUDGE_MODEL,
            rubric_hash=text_hash(rubric_path),
        ),
    }


class TestJudgeAgreesWithHumanScores:
    """R7.11 — measured against the reviewer, and reported with what it was measured on."""

    def test_the_sample_is_large_enough_to_mean_anything(self, measured: dict):
        """Example 1's precondition, and the reason the threshold is still OPEN.

        Twenty is the spec's number. Below it the honest report is "not
        measurable at this N", so there is nothing for a threshold to gate.
        """
        assert len(measured["human"]) >= MINIMUM_SAMPLE

        print(f"\n  judge:      {JUDGE_MODEL}")
        print(f"  sample:     {len(measured['human'])} human-scored root_cause cases")
        print(f"  agreement:  {measured['agreement']:.1%}")
        print(f"  disagreed:  {', '.join(measured['disagreed']) or 'none'}")
        for case in measured["disagreed"]:
            print(
                f"    {case}: human={measured['human'][case]} "
                f"judge={measured['verdicts'][case]} — {measured['evidence'][case][:160]}"
            )

    def test_the_figure_carries_the_judge_and_the_sample_size(self, measured: dict):
        """Example 2: the one where the number is reproducible.

        A figure without the model that produced it and the sample it came from
        says a judge agreed with a human, without saying which judge, on what
        question, or over how much (R7.6 needs both to notice a stale one).
        """
        recorded: Calibration = measured["calibration"]

        assert recorded.judge_model == JUDGE_MODEL
        assert recorded.sample_size == len(measured["human"])
        assert recorded.rubric_hash and len(recorded.rubric_hash) == 64
        assert 0.0 <= recorded.agreement <= 1.0

    def test_a_smaller_sample_is_refused_rather_than_reported(self, measured: dict):
        """Example 3: the one with fewer than twenty cases.

        Refused as not measurable, never rounded into a percentage. A figure from
        five cases reads exactly like a figure from fifty.
        """
        thin = measured["calibration"].model_copy(update={"sample_size": 5})

        with pytest.raises(NotCalibrated):
            is_eligible(thin, threshold=0.8)

    def test_only_the_judged_field_is_measured(self, measured: dict):
        """Counter-example (row 4): the deterministic fields are not in this figure.

        Mixing them in would flatter the judge with cases it never scored --
        `loss_amount` and `resolution_date` are exact comparisons, and a judge
        gets no credit for arithmetic it did not do (R7.1, R7.10).
        """
        assert {case["field"] for case in cases()} == {"root_cause"}
        assert {case["rule"] for case in cases()} == {"R7.11"}

    def test_the_agreed_threshold_is_met(self, measured: dict):
        """Example 1: the one this rule exists for.

        Skipped until the threshold is a number the domain expert agreed. The
        measurement above is what that conversation is held over.
        """
        if THRESHOLD is None:
            pytest.skip(
                "R7.11's threshold is OPEN. The measured figure is reported above; "
                "set THRESHOLD once it is agreed, and the rule becomes assertable."
            )

        assert is_eligible(measured["calibration"], threshold=THRESHOLD)
