"""R7.33 — a judged `per_group` field is put to the judge with every member of its group.

The judge is asked whether an answer is supported by its evidence, and the
evidence of a group's answer is the group. A claim may stand on two members --
the master's right to terminate on notice, with the date amendment 3 set -- so
shown only the member the field cites, the judge would weigh half the evidence.
It is shown the group as the stage was: every member under its own key, in key
order. Its verdict is keyed on all of them (R7.18), and a calibration case
naming the group is judged the same way.

Through the CLI -- `run`, `eval`, `calibrate` -- because what a judge is shown
is assembled where the command reads the workspace. The model and the judge are
fakes; the judge remembers every question it was asked (R0.1).
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline

from dossier.application.eval import judge_prompt_hash
from dossier.domain.hashing import text_hash

PIPELINE = "contract-renewal"
GOLD = "gold/contracts"
MODEL = "anthropic:claude-sonnet-4-5-20250929"
FIELD = "termination_terms"
DECLARATION = f"fields:\n  {FIELD}: {{kind: free_text, judge: rubrics/termination.md}}\n"
RUBRIC = "Are the stated termination terms supported by the contract?\n"
TERMS = "Either party may terminate on 90 days' notice before 2027-03-31."
CONTRACTS = {
    "ACME-2024/amendment-1.md": "# Amendment 1\n\nThe invoicing address changes.\n",
    "ACME-2024/amendment-3.md": "# Amendment 3\n\nThe term is extended to 2027-03-31.\n",
    "ACME-2024/master.md": "# ACME master\n\nEither party may terminate on 90 days' notice.\n",
    "GLOBEX-2023/master.md": "# GLOBEX master\n\nThe term ends 2026-12-31.\n",
}
ACME = ["ACME-2024/amendment-1.md", "ACME-2024/amendment-3.md", "ACME-2024/master.md"]
MEMBER = re.compile(r'<document key="([^"]+)">')


class Model:
    """The stage: ACME's terms cited from amendment 3; GLOBEX states none.

    A call shown any other document -- the judge's question has a `<claim>` --
    is answered as the judge, and remembered.
    """

    model_id = MODEL

    def __init__(self) -> None:
        self.judged: list[str] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        if "<claim>" in prompt:
            self.judged.append(prompt)
            return json.dumps({"supported": True, "evidence": "amendment 3 sets the date"})
        shown = MEMBER.findall(prompt)
        if shown[0].startswith("ACME-2024/"):
            fields = [
                {
                    "field": FIELD,
                    "value": TERMS,
                    "source": {"document": "ACME-2024/amendment-3.md", "span": "2027-03-31"},
                }
            ]
        else:
            fields = [{"field": FIELD, "value": None, "reason": "not stated in document"}]
        return json.dumps({"document": shown[0], "fields": fields})


def _gold(document: str, value) -> str:
    field = {"value": value} if value else {"value": None, "reason": "not stated"}
    return json.dumps(
        {
            "document": document,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-27",
            "fields": {FIELD: field},
        }
    )


def _workspace(workspace: Path, monkeypatch, model: Model, *, mode: str = "per_group") -> Path:
    """Two contracts, a step judging one free-text field, and a calibrated bar.

    Gold verifies what the step answers for: each contract for `per_group`, and
    amendment 3 alone for `per_file`.
    """
    import dossier.cli.main as cli

    for key, text in CONTRACTS.items():
        path = workspace / "inbox" / "contracts" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: contracts\n    type: folder\n    path: inbox/contracts/\n",
        encoding="utf-8",
    )
    pipeline = write_pipeline(
        workspace,
        name=PIPELINE,
        sources=["contracts"],
        modes={"extract": mode},
        outputs={"extract": "schemas/contract.yaml"},
    ).parent
    (pipeline / "schemas" / "contract.yaml").write_text(DECLARATION, encoding="utf-8")
    (pipeline / "rubrics" / "termination.md").write_text(RUBRIC, encoding="utf-8")

    gold = workspace / GOLD
    (gold / "calibrations").mkdir(parents=True)
    if mode == "per_group":
        (gold / "ACME-2024.json").write_text(_gold("ACME-2024", TERMS), encoding="utf-8")
        (gold / "GLOBEX-2023.json").write_text(_gold("GLOBEX-2023", None), encoding="utf-8")
    else:
        (gold / "amendment-3.json").write_text(
            _gold("ACME-2024/amendment-3.md", TERMS), encoding="utf-8"
        )
    (gold / "judge.yaml").write_text(f"{FIELD}: 0.95\n", encoding="utf-8")
    (gold / "calibrations" / f"{FIELD}.json").write_text(
        json.dumps(
            {
                "judge_model": MODEL,
                "rubric_hash": text_hash(pipeline / "rubrics" / "termination.md"),
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


class TestAGroupFieldIsJudgedAgainstEveryMember:
    """R7.33 — the judge is shown the group as the stage was."""

    def test_the_judge_is_shown_every_member_in_key_order(self, workspace: Path, monkeypatch):
        """Row 1: the one where the terms stand on the master and amendment 3.

        The field cites amendment 3; the judge is shown all three ACME files,
        each under its own key, and none of GLOBEX's.
        """
        model = Model()
        _workspace(workspace, monkeypatch, model)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        (question,) = model.judged
        assert MEMBER.findall(question) == ACME

    def test_a_group_with_a_new_member_is_judged_again(self, workspace: Path, monkeypatch):
        """Row 2: the one where amendment 4 is filed and the contract run again.

        The verdict is keyed on every member's text (R7.18), so the same
        candidate over four members is a new question.
        """
        model = Model()
        _workspace(workspace, monkeypatch, model)
        assert _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD).exit_code == 0
        amendment = workspace / "inbox" / "contracts" / "ACME-2024" / "amendment-4.md"
        amendment.write_text("# Amendment 4\n\nA site is added.\n", encoding="utf-8")
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        # An eval scores the latest run, and two runs in one second sort by their
        # random suffix. The first run's directory goes, so the latest is the
        # four-member one; its cached verdicts stay, which is what is at stake.
        shutil.rmtree(workspace / "runs")
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(model.judged) == 2
        assert "ACME-2024/amendment-4.md" in MEMBER.findall(model.judged[1])

    def test_a_calibration_case_naming_the_group_is_judged_against_its_members(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the sample was written for contracts.

        A case names `ACME-2024` as its document, and is put to the judge with
        the three files, as an eval's question is.
        """
        model = Model()
        _workspace(workspace, monkeypatch, model)
        cases = [
            {
                "document": "ACME-2024",
                "answer": f"candidate terms {index}",
                "supported": index < 12,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-27",
            }
            for index in range(20)
        ]
        samples = workspace / GOLD / "samples"
        samples.mkdir()
        (samples / f"{FIELD}.jsonl").write_text(
            "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
        )

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert len(model.judged) == 20
        assert all(MEMBER.findall(question) == ACME for question in model.judged)

    def test_a_per_file_field_is_judged_against_its_one_document(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where the step did not ask for groups.

        A `per_file` step's judge is shown the document its answer is about,
        as it always was (R7.17): its text, with no member wrapped inside it.
        """
        model = Model()
        _workspace(workspace, monkeypatch, model, mode="per_file")

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        (question,) = model.judged
        assert "Document ACME-2024/amendment-3.md, in full" in question
        assert MEMBER.findall(question) == []
