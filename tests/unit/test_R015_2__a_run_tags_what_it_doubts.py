"""R15.2 — a run tags the trace of every document it doubts, and names the fields
it doubts.

Which verdicts are doubts is the domain's decision (`review_tags`): a document
that failed, and a field `ungrounded` or `invalid` (R6.16); never `described`,
which a judge decides (R7.21), nor an abstention, which is a valid answer
(R6.5). Then the run, through `execute` and a `FakeTracker`, which keeps the
tags each trace was closed with; and `MlflowTracker`, which sets them on the
trace MLflow is holding, where the queue filter finds them.

Three of the scoring example's incidents: `INC-4821` abstains on every field,
`INC-4822` answers `loss_amount` from a span its text does not hold and
`root_cause` with a bare null, and `INC-4901` is answered with something that
is not JSON, twice (R6.2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fakes import FakeModelClient, FakeTracker
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES, abstains, found

from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.grounding import FieldVerdict
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.tracking import review_tags

NEEDED = {"dossier.review": "needed"}
NONSENSE = "no JSON here"


class TestWhichDoubtsAreTagged:
    """R15.2 — the decision: which verdicts are doubts, and how they are named."""

    def test_an_ungrounded_field_is_a_doubt_named_with_its_reason(self):
        """Row 1: `loss_amount` ungrounded."""
        tags = review_tags(failed=False, verdicts=[("loss_amount", FieldVerdict.UNGROUNDED)])

        assert tags == {**NEEDED, "dossier.findings": "loss_amount: ungrounded"}

    def test_a_document_that_failed_is_a_doubt(self):
        """Row 2: nothing was answered, so there is no field to name."""
        assert review_tags(failed=True, verdicts=[]) == {**NEEDED, "dossier.findings": "failed"}

    def test_several_doubts_are_named_by_field(self):
        """Row 3: `root_cause` invalid and `loss_amount` ungrounded, sorted by field."""
        tags = review_tags(
            failed=False,
            verdicts=[
                ("root_cause", FieldVerdict.INVALID),
                ("severity", FieldVerdict.VALID),
                ("loss_amount", FieldVerdict.UNGROUNDED),
            ],
        )

        assert tags["dossier.findings"] == "loss_amount: ungrounded; root_cause: invalid"

    def test_an_answer_with_nothing_doubtful_is_not_tagged(self):
        """Row 5, a counter-example: grounded and abstaining fields only."""
        verdicts = [("loss_amount", FieldVerdict.VALID), ("root_cause", FieldVerdict.ABSTAINED)]

        assert review_tags(failed=False, verdicts=verdicts) == {}

    def test_a_described_field_is_not_a_doubt(self):
        """Row 6, a counter-example: read off a picture, and left to the judge (R7.21)."""
        assert (
            review_tags(failed=False, verdicts=[("root_cause", FieldVerdict.DESCRIBED)]) == {}
        )


def _answers() -> list[str]:
    """What the model says, in the order `extract` asks: 4821, 4822, then 4901 twice."""
    doubtful = {
        "document": "INC-4822",
        "fields": [
            found("INC-4822", "loss_amount", 90000.0, "a sentence INC-4822 does not hold"),
            {"field": "root_cause", "value": None},
        ],
    }
    clean = {"document": "INC-4821", "fields": [abstains("loss_amount")]}
    return [json.dumps(clean), json.dumps(doubtful), NONSENSE, NONSENSE]


def _run(workspace: Path, model, *, run_id: str = "20260806T142203Z-4f1a") -> FakeTracker:
    from dossier.infrastructure.cache import ArtifactCache

    tracker = FakeTracker()
    execute(
        workspace=workspace,
        pipeline=PipelineConfig(
            name="incident-audit",
            sources=["incidents-jira"],
            model="anthropic:claude-sonnet-4-5-20250929",
            steps=[
                StepConfig(
                    id="extract",
                    prompt="prompts/extract.md",
                    input="documents",
                    mode="per_file",
                    output="schemas/incident.yaml",
                )
            ],
        ),
        pipeline_hash="6e0d4b27" * 8,
        documents={
            "INC-4821": "a3f9c1e2" * 8,
            "INC-4822": "77c1b40a" * 8,
            "INC-4901": "0e52dd18" * 8,
        },
        document_text={key: ISSUES[key] for key in ("INC-4821", "INC-4822", "INC-4901")},
        schemas={
            "extract": OutputSchema(schema={"type": "object"}, declaration_hash="d24c86e1" * 8)
        },
        prompts={"extract": prompt_for(["documents"])},
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        tracker=tracker,
        experiment="dossier-audit/incident-audit/run",
    )
    return tracker


def _tags(tracker: FakeTracker) -> dict[str, dict[str, str]]:
    """Each document's review tags, the step and document tags set aside."""
    return {
        trace.tags["dossier.document"]: {
            key: value
            for key, value in trace.tags.items()
            if key.startswith("dossier.review") or key == "dossier.findings"
        }
        for trace in tracker.traces
    }


class TestARunTagsWhatItDoubts:
    """R15.2 — through `execute`: the queue a reviewer filters on."""

    def test_each_trace_carries_the_doubts_of_its_document(self, tmp_path: Path):
        """Rows 1-3 and 5: a clean answer, two doubtful fields, and a failure."""
        tracker = _run(tmp_path, FakeModelClient(responses=_answers()))

        assert _tags(tracker) == {
            "INC-4821": {},
            "INC-4822": {
                **NEEDED,
                "dossier.findings": "loss_amount: ungrounded; root_cause: invalid",
            },
            "INC-4901": {**NEEDED, "dossier.findings": "failed"},
        }

    def test_a_doubt_served_from_cache_is_tagged_again(self, tmp_path: Path):
        """Row 4: the same run again; `INC-4901` failed, so it is asked again and fails."""
        first = _run(tmp_path, FakeModelClient(responses=_answers()))

        again = _run(
            tmp_path,
            FakeModelClient(responses=[NONSENSE, NONSENSE]),
            run_id="20260807T090000Z-bbbb",
        )

        assert _tags(again) == _tags(first)


class _Client:
    """`MlflowClient` as far as one trace goes: the tags set on it, and when."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_experiment_by_name(self, name):
        return None

    def create_experiment(self, name):
        return "1"

    def create_run(self, experiment_id, tags=None, run_name=None):
        return SimpleNamespace(info=SimpleNamespace(run_id="run-1"))

    def start_trace(self, *, name, tags, experiment_id, run_id, **given):
        return SimpleNamespace(trace_id="tr-0", span_id="root")

    def set_trace_tag(self, trace_id, key, value):
        self.calls.append(("tag", trace_id, key, value))

    def end_trace(self, trace_id, attributes=None, status=None, **given):
        self.calls.append(("end", trace_id))


@pytest.fixture
def client(monkeypatch) -> _Client:
    mlflow = pytest.importorskip("mlflow")

    stand_in = _Client()
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "MlflowClient", lambda tracking_uri=None: stand_in)
    return stand_in


class TestMlflowHoldsTheTags:
    """R15.2, on `MlflowTracker`: set on the trace before it closes."""

    def test_the_tags_are_set_on_the_trace_before_it_ends(self, client: _Client):
        """Row 1: what the queue filter `tags.`dossier.review` = 'needed'` finds."""
        from dossier.infrastructure.tracking.mlflow import MlflowTracker

        tracker = MlflowTracker("http://localhost:5000")
        tracker.start_run(experiment="dossier-audit/incident-audit/run", name="r", tags={})
        tracker.start_trace(name="extract · INC-4822", tags={})

        tracker.end_trace(
            status="OK", tags={**NEEDED, "dossier.findings": "loss_amount: ungrounded"}
        )

        assert client.calls == [
            ("tag", "tr-0", "dossier.review", "needed"),
            ("tag", "tr-0", "dossier.findings", "loss_amount: ungrounded"),
            ("end", "tr-0"),
        ]
