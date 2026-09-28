"""R7.34 — a judged field of a step that reads `reference` is put to the judge
with every reference document beside the evidence it was answered from.

The judge asks whether an answer is supported by its evidence, and a step
reading `reference` answered from its document and the procedures together
(R3.18). "Escalation came 40 minutes late" stands on the incident's timeline
and on the 30 minutes `OPS-114` allows; shown the incident alone, a judge would
call a supported claim unsupported. So it is shown what the stage was shown.

Rows 1, 2, 3 and 5 go through the CLI -- `run`, `eval`, `calibrate` -- because
what a judge is shown is assembled where the command reads the workspace. Row 4
calls `judge_scores` directly, as R7.21's tests do, because a `described` field
needs a run that read pages. The model and the judge are fakes; the judge
remembers every question it was asked (R0.1). Folder sources, so keys carry the
extension; the incident is kept in `inbox/tickets/` because the workspace
fixture fills `inbox/incidents/`.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.fakes import FakeModelClient
from tests.pipelines import write_pipeline

from dossier.application.eval import SHOWN_AS_PAGES, Judging, judge_prompt_hash, judge_scores
from dossier.application.extract import DocumentResult
from dossier.application.run import StepReport, reference_context
from dossier.domain.grounding import FieldCheck, FieldVerdict
from dossier.domain.hashing import text_hash
from dossier.domain.ports import ImagePart
from dossier.domain.schemas import FieldRecord
from dossier.domain.scoring import DocumentScore, FieldScore, Verdict

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
DECLARATION = "fields:\n  root_cause: {kind: free_text, judge: rubrics/root_cause.md}\n"
CAUSE = "Escalation came 40 minutes late"
TICKET = "INC-4821.md"
OPS_114 = "OPS-114.md"
V37 = "# OPS-114 Incident escalation\n\nEscalate within 30 minutes.\n"
V38 = "# OPS-114 Incident escalation\n\nEscalate within 15 minutes.\n"
SHOWN = re.compile(r'<document key="([^"]+)">')
SUPPORTED = json.dumps({"supported": True, "evidence": "OPS-114 allows 30 minutes"})


class Model:
    """The stage, answering `root_cause` from the incident; and the judge, remembered.

    A call whose prompt holds a `<claim>` is the judge's.
    """

    model_id = MODEL

    def __init__(self) -> None:
        self.judged: list[str] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        if "<claim>" in prompt:
            self.judged.append(prompt)
            return SUPPORTED
        cited = {"document": TICKET, "span": CAUSE}
        field = {"field": "root_cause", "value": CAUSE, "source": cited}
        return json.dumps({"document": TICKET, "fields": [field]})


def _workspace(workspace: Path, monkeypatch, model: Model, *, verifying: str) -> Path:
    """One incident, one procedure as reference, one step judging `root_cause`, a bar met."""
    import dossier.cli.bootstrap as cli

    ticket = workspace / "inbox" / "tickets" / TICKET
    ticket.parent.mkdir(parents=True)
    ticket.write_text(f"# INC-4821\n\n{CAUSE}.\n", encoding="utf-8")
    procedure = workspace / "inbox" / "procedures" / OPS_114
    procedure.parent.mkdir(parents=True)
    procedure.write_text(V37, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: tickets\n    type: folder\n    path: inbox/tickets/\n"
        "  - id: procedures\n    type: folder\n    path: inbox/procedures/\n",
        encoding="utf-8",
    )
    pipeline = write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["tickets"],
        reference=["procedures"],
        steps=["verify"],
        inputs={"verify": verifying},
        outputs={"verify": "schemas/cause.yaml"},
    ).parent
    (pipeline / "schemas" / "cause.yaml").write_text(DECLARATION, encoding="utf-8")

    gold = workspace / GOLD
    (gold / "calibrations").mkdir(parents=True)
    (gold / "INC-4821.json").write_text(
        json.dumps(
            {
                "document": TICKET,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-27",
                "fields": {"root_cause": {"value": CAUSE}},
            }
        ),
        encoding="utf-8",
    )
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": MODEL,
                "rubric_hash": text_hash(pipeline / "rubrics" / "root_cause.md"),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    return workspace


READING = "[documents, reference]"


class TestAFieldThatReadReferenceIsJudgedWithIt:
    """R7.34 — the judge is shown the context the stage was shown."""

    def test_the_judge_is_shown_the_incident_and_the_procedure(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where the claim stands on the incident and `OPS-114`."""
        model = Model()
        _workspace(workspace, monkeypatch, model, verifying=READING)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        (question,) = model.judged
        assert SHOWN.findall(question) == [TICKET, OPS_114]
        assert "Escalate within 30 minutes." in question

    def test_a_procedure_edited_asks_the_judge_again(self, workspace: Path, monkeypatch):
        """Row 2: the one where `OPS-114` moves to `v38` and the run is made again.

        The candidate is the same; the evidence is not, so the verdict key moves.
        """
        model = Model()
        _workspace(workspace, monkeypatch, model, verifying=READING)
        assert _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD).exit_code == 0
        (workspace / "inbox" / "procedures" / OPS_114).write_text(V38, encoding="utf-8")
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        # An eval scores the latest run, and two runs in one second sort by their
        # random suffix. The first run's directory goes, so the latest is the one
        # after the edit; the cached verdicts stay, which is what is at stake.
        shutil.rmtree(workspace / "runs")
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(model.judged) == 2
        assert "Escalate within 15 minutes." in model.judged[1]

    def test_a_calibration_case_is_judged_with_the_procedure(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the sample was written for `verify`'s field."""
        model = Model()
        _workspace(workspace, monkeypatch, model, verifying=READING)
        samples = workspace / GOLD / "samples"
        samples.mkdir()
        cases = [
            {
                "document": TICKET,
                "answer": f"candidate cause {index}",
                "supported": index < 12,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-27",
            }
            for index in range(20)
        ]
        (samples / "root_cause.jsonl").write_text(
            "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
        )

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(model.judged) == 20
        assert all(SHOWN.findall(question) == [TICKET, OPS_114] for question in model.judged)

    def test_a_described_field_is_shown_the_pages_then_the_procedure(self):
        """Row 4: the one where the stage read a page as well as the procedures.

        The pages as R7.21 shows them, then `OPS-114` under its own key. A
        different `OPS-114` is different evidence, and a different verdict key.
        """
        page = ImagePart(media_type="image/png", data=b"INC-5720 page 1")
        chart = "INC-5720-checkout-latency-postmortem.png"
        model = FakeModelClient(responses=[SUPPORTED, SUPPORTED])
        cache = _Cache()
        record = FieldRecord.model_validate(
            {"field": "root_cause", "value": CAUSE, "source": {"document": chart, "span": "x"}}
        )
        report = StepReport(
            step="verify",
            results=(
                DocumentResult(
                    document=chart,
                    records=(record,),
                    checks=(FieldCheck(FieldVerdict.DESCRIBED, "on the page"),),
                ),
            ),
        )
        score = DocumentScore(
            document=chart,
            results=(FieldScore("root_cause", Verdict.NEEDS_JUDGE, "free text"),),
        )

        for text in (V37, V38):
            judge_scores(
                [score],
                report=report,
                judging=Judging(
                    model=model,
                    cache=cache,
                    documents={},
                    parts={chart: [page]},
                    context=reference_context({OPS_114: text}),
                    rubrics={"root_cause": ("is it supported?", "r" * 64)},
                    judge_model=MODEL,
                    run_id="20260927T000000Z-0001",
                    dossier_version="0.1.0",
                ),
            )

        assert model.call_count == 2
        first = str(model.calls[0]["prompt"])
        assert SHOWN_AS_PAGES in first
        assert SHOWN.findall(first) == [OPS_114]
        assert model.calls[0]["parts"] == (page,)

    def test_a_step_that_does_not_read_reference_is_judged_on_its_document(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, a counter-example: the one where the step reads `documents` only.

        Shown its one document, as R7.17 always showed it, and no procedure.
        """
        model = Model()
        _workspace(workspace, monkeypatch, model, verifying="documents")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        (question,) = model.judged
        assert f"Document {TICKET}, in full" in question
        assert SHOWN.findall(question) == []


class _Cache:
    """An artifact store that keeps what it is given."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}

    def get(self, key: str, *, require_record: bool = False) -> bytes | None:
        return self.entries.get(key)

    def put(self, key: str, payload: bytes, *, record=None) -> None:
        self.entries[key] = payload

    def record(self, key: str):
        return None
