"""R15.3 — `dossier review pull` writes every valid human verdict on a pipeline's
runs, and reports them by step and name.

Three layers, each where its decision is:

- the domain writes `feedback.jsonl` and the report from verdicts it is handed
  (`dossier.domain.review`), so the bytes and the words are decided once;
- the application writes the file, or nothing, from whatever `ReviewSource` it
  is given (`dossier.application.review`);
- `MlflowReviewSource` decides which of MLflow's assessments are a reviewer's
  verdicts: source `HUMAN`, still valid, and on a trace a run of this pipeline
  wrote. Tested against a stand-in `MlflowClient` answering as MLflow 3.15.1
  did in the spike spec 015 was written from.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.fakes import FakeReviewSource

from dossier.application.review import pull_reviews
from dossier.domain.review import Verdict, feedback_jsonl, review_report

RUN = "20260806T142203Z-4f1a"
EXPERIMENT = "dossier-audit/incident-audit/run"
REASON = "payments stopped for an hour: major, not minor"


def verdict(**overrides) -> Verdict:
    """`s.brunner`'s thumbs-down on `extract · INC-4822`, as the trace view records it."""
    fields = {
        "run": RUN,
        "step": "extract",
        "document": "INC-4822",
        "name": "severity",
        "kind": "feedback",
        "value": False,
        "rationale": REASON,
        "reviewer": "User",
        "at": "2026-09-24T09:12:40Z",
        "trace": "tr-4822",
        "assessment": "a-0001",
    }
    return Verdict(**{**fields, **overrides})


class TestTheFileAndTheReport:
    """R15.3 — what is written and what is said, from the verdicts alone."""

    def test_a_verdict_is_one_line_naming_where_what_and_who(self):
        """Row 1: the run, step, document, name, kind, value, reason, author and time."""
        (line,) = feedback_jsonl([verdict()]).splitlines()

        assert line == (
            '{"assessment": "a-0001", "at": "2026-09-24T09:12:40Z", "document": "INC-4822", '
            '"kind": "feedback", "name": "severity", "rationale": "' + REASON + '", '
            '"reviewer": "User", "run": "' + RUN + '", "step": "extract", '
            '"trace": "tr-4822", "value": false}'
        )

    def test_the_file_is_the_same_bytes_whatever_order_the_server_answered_in(self):
        """Row 4's precondition: sorted, so a second pull rewrites the same bytes."""
        first = verdict()
        second = verdict(step="verify", name="overall", value=True, assessment="a-0002")

        assert feedback_jsonl([second, first]) == feedback_jsonl([first, second])
        assert feedback_jsonl([first]).endswith("\n")

    def test_the_report_counts_by_step_and_name_and_gives_each_no_its_reason(self):
        """Rows 1 and 5: a no on `extract`'s `severity`, a yes on `verify`'s `overall`."""
        lines = review_report(
            [verdict(), verdict(step="verify", name="overall", value=True, rationale=None)]
        )

        assert lines == [
            "extract  severity  0 yes · 1 no",
            f"    INC-4822  User: {REASON}",
            "verify  overall  1 yes · 0 no",
        ]

    def test_an_author_is_reported_as_recorded(self):
        """Row 5: a verdict logged through the API as `s.brunner` is `s.brunner`'s."""
        lines = review_report([verdict(reviewer="s.brunner")])

        assert lines[1] == f"    INC-4822  s.brunner: {REASON}"

    def test_an_expected_value_is_not_counted_as_a_yes_or_a_no(self):
        """R15.4's half: an expectation is written to the file and counted apart."""
        expected = verdict(kind="expectation", value="major", rationale=None)

        assert '"kind": "expectation"' in feedback_jsonl([expected])
        assert review_report([expected]) == ["extract  severity  1 value expected"]


class TestThePullWritesTheFileOrNothing:
    """R15.3 — through `pull_reviews`, from whatever source it is handed."""

    def test_a_pull_writes_every_verdict(self, tmp_path: Path):
        """Row 1: `review/incident-audit/feedback.jsonl`."""
        source = FakeReviewSource({EXPERIMENT: [verdict()]})
        directory = tmp_path / "review" / "incident-audit"

        pulled = pull_reviews(source, experiment=EXPERIMENT, directory=directory)

        assert pulled == [verdict()]
        assert (directory / "feedback.jsonl").read_text(encoding="utf-8") == (
            feedback_jsonl([verdict()])
        )

    def test_a_second_pull_with_nothing_new_rewrites_the_same_bytes(self, tmp_path: Path):
        """Row 4: `git diff` shows nothing, because nothing is new."""
        source = FakeReviewSource({EXPERIMENT: [verdict(), verdict(assessment="a-0002")]})
        directory = tmp_path / "review" / "incident-audit"
        pull_reviews(source, experiment=EXPERIMENT, directory=directory)
        before = (directory / "feedback.jsonl").read_bytes()

        pull_reviews(source, experiment=EXPERIMENT, directory=directory)

        assert (directory / "feedback.jsonl").read_bytes() == before

    def test_no_verdict_writes_nothing(self, tmp_path: Path):
        """Row 7, a counter-example: no reviewer has said anything yet."""
        directory = tmp_path / "review" / "incident-audit"

        pulled = pull_reviews(FakeReviewSource({}), experiment=EXPERIMENT, directory=directory)

        assert pulled == []
        assert not directory.exists()


def _assessment(
    name: str,
    value,
    *,
    source: str = "HUMAN",
    by: str = "User",
    valid: bool | None = True,
    expectation: bool = False,
    at: int = 1790241160000,
    identifier: str = "a-0001",
    rationale: str | None = REASON,
):
    """An assessment as `search_traces` returns one: feedback, or an expectation."""
    return SimpleNamespace(
        assessment_id=identifier,
        name=name,
        source=SimpleNamespace(source_type=source, source_id=by),
        create_time_ms=at,
        rationale=rationale,
        valid=valid,
        feedback=None if expectation else SimpleNamespace(value=value),
        expectation=SimpleNamespace(value=value) if expectation else None,
    )


def _trace(trace_id: str, document: str, *assessments, step: str = "extract", run="run-1"):
    return SimpleNamespace(
        info=SimpleNamespace(
            trace_id=trace_id,
            tags={"dossier.step": step, "dossier.document": document},
            request_metadata={"mlflow.sourceRun": run},
            assessments=list(assessments),
        )
    )


class _Client:
    """`MlflowClient`, as far as reading a pipeline's traces back goes."""

    def __init__(self, pages: list[list], *, experiment: str | None = "7") -> None:
        self.pages = pages
        self.experiment = experiment
        self.searched: list[dict] = []

    def get_experiment_by_name(self, name):
        return (
            None if self.experiment is None else SimpleNamespace(experiment_id=self.experiment)
        )

    def search_traces(self, **query):
        self.searched.append(query)
        page = len(self.searched) - 1
        token = str(page + 1) if page + 1 < len(self.pages) else None
        return _Paged(self.pages[page], token)

    def get_run(self, run_id):
        return SimpleNamespace(info=SimpleNamespace(run_name={"run-1": RUN}[run_id]))


class _Paged(list):
    def __init__(self, items, token):
        super().__init__(items)
        self.token = token


@pytest.fixture
def mlflow_client(monkeypatch):
    mlflow = pytest.importorskip("mlflow")

    holder = SimpleNamespace(client=None)
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "MlflowClient", lambda tracking_uri=None: holder.client)
    return holder


class TestMlflowKeepsAReviewersVerdicts:
    """R15.3 rows 1-3, on `MlflowReviewSource`: which assessments are verdicts."""

    def _read(self, holder, client: _Client) -> list[Verdict]:
        from dossier.infrastructure.tracking.mlflow import MlflowReviewSource

        holder.client = client
        return MlflowReviewSource("http://localhost:5000").human_verdicts(experiment=EXPERIMENT)

    def test_a_reviewers_feedback_is_read_with_where_who_and_when(self, mlflow_client):
        """Row 1: the trace view's thumbs-down, author `User`, on the run it was left on."""
        client = _Client([[_trace("tr-4822", "INC-4822", _assessment("severity", False))]])

        assert self._read(mlflow_client, client) == [verdict()]

    def test_an_overridden_verdict_is_read_as_its_override(self, mlflow_client):
        """Row 2: `j.okafor`'s yes replaced the no, which MLflow marks invalid."""
        trace = _trace(
            "tr-4822",
            "INC-4822",
            _assessment("severity", False, valid=False),
            _assessment("severity", True, identifier="a-0002", rationale=None),
        )

        (read,) = self._read(mlflow_client, _Client([[trace]]))

        assert (read.value, read.assessment) == (True, "a-0002")

    def test_the_judges_verdicts_are_not_a_reviewers(self, mlflow_client):
        """Row 3: an `LLM_JUDGE` feedback from an eval (R11.16), and a `CODE` one."""
        trace = _trace(
            "tr-4822",
            "INC-4822",
            _assessment("root_cause", True, source="LLM_JUDGE", by="openai:gpt-5.4-mini"),
            _assessment("severity", True, source="CODE", identifier="a-0002"),
        )

        assert self._read(mlflow_client, _Client([[trace]])) == []

    def test_an_expectation_is_read_as_one(self, mlflow_client):
        """R15.4's source: the value a reviewer expected."""
        trace = _trace(
            "tr-4822",
            "INC-4822",
            _assessment("severity", "major", expectation=True, valid=None, rationale=None),
        )

        (read,) = self._read(mlflow_client, _Client([[trace]]))

        assert (read.kind, read.value) == ("expectation", "major")

    def test_every_page_is_read(self, mlflow_client):
        """A pipeline reviewed for a year has more traces than one page holds."""
        client = _Client(
            [
                [_trace("tr-4821", "INC-4821", _assessment("overall", True, identifier="a-1"))],
                [_trace("tr-4822", "INC-4822", _assessment("severity", False))],
            ]
        )

        read = self._read(mlflow_client, client)

        assert [item.document for item in read] == ["INC-4821", "INC-4822"]
        assert client.searched[1]["page_token"] == "1"

    def test_a_pipeline_never_run_has_nothing_to_read(self, mlflow_client):
        """Row 7's precondition: no run experiment yet, so no verdict."""
        assert self._read(mlflow_client, _Client([[]], experiment=None)) == []
