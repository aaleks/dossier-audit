"""R21.1 — a masked pipeline's run and eval show no model a value its masker detects.

The acceptance rule of spec 021's first part. It is an acceptance test because
no single layer can make it true: the pipeline declares `masking:`, the run
masks each document and each reference document before rendering a prompt,
grounding checks a quote against the text the model was shown, and `eval`
shows its judge the evidence the step was shown -- through `replayed_inputs`,
which is a second road to a model that a mask applied at one call site would
miss.

`PLAY-6001` is the canary corpus's English note (`_fixtures.md`, "Client
identifying data"): `Hans Muster` is named before `Erika Mustermann`, so they
mask as `[PERSON_1]` and `[PERSON_2]`. `OPS-114` is the escalation procedure,
here naming a client too, because `reference` is shown to a model as much as a
document is (R3.18).

The masker is `FakeMasker`, which finds the canaries by their exact text and
counts its calls; the model records every prompt it is sent. No Presidio, no
network: what this rule claims is the mechanism, and the detection is R21.12's.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.fakes import CANARIES, FakeMasker, FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, IssueTracker, abstains, found

from dossier.domain.hashing import text_hash

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
GOLD = "gold/masked"
JUDGED = "root_cause"
URI = "http://localhost:5000"

CAUSE = "the settlement export was scheduled at a local time that did not exist"
PLAY_6001 = (
    "# PLAY-6001\n\n"
    "Hans Muster reported that the nightly settlement export never ran.\n"
    "The affected client is Erika Mustermann (erika.mustermann@example.ch, "
    "phone +41 44 555 01 23), account CH93 0076 2011 6238 5295 7.\n"
    f"Root cause: {CAUSE}.\n"
)
OPS_114 = (
    "# OPS-114 Incident escalation procedure\n\n"
    "Escalate within 30 minutes. For the pilot client, call Hans Muster first.\n"
)
SOURCES = f"""\
sources:
  - id: {SOURCE_ID}
    type: {SOURCE_TYPE}
  - id: procedures
    type: folder
    path: inbox/procedures/
"""
DECLARATION = """\
masker: presidio
languages: [en]
score_threshold: 0.5
entities: [PERSON, EMAIL_ADDRESS, PHONE_NUMBER, IBAN_CODE]
"""


class Model:
    """Answers the step and the judge, and remembers every prompt it was sent.

    The step's answer cites the cause, which holds no client data, so it is
    grounded whether the model was shown the masked text or the converted
    one: this rule is about what was shown, not about what was extracted.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.judged: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.prompts.append(prompt)
        if schema is not None and "supported" in (schema.get("properties") or {}):
            self.judged.append(prompt)
            return json.dumps({"supported": True, "evidence": "the cause is stated"})
        return json.dumps(
            {
                "document": "PLAY-6001",
                "fields": [
                    *(abstains(field) for field in FIELDS if field != JUDGED),
                    found("PLAY-6001", JUDGED, CAUSE, CAUSE),
                ],
            }
        )


def _held(prompts: list[str]) -> list[str]:
    """Every canary any of the prompts holds, in the order `CANARIES` lists them."""
    return [value for value in CANARIES if any(value in prompt for prompt in prompts)]


def _gold(workspace: Path) -> None:
    """`PLAY-6001`'s verified cause, its judge's bar, and a calibration clearing it (R7.15).

    A gold set of its own, so the workspace's four incidents, which this run does
    not hold, are not what the eval talks about.
    """
    from dossier.application.eval import judge_prompt_hash

    gold = workspace / GOLD
    (gold / "calibrations").mkdir(parents=True)
    (gold / "judge.yaml").write_text(f"{JUDGED}: 0.95\n", encoding="utf-8")
    (gold / "PLAY-6001.json").write_text(
        json.dumps(
            {
                "document": "PLAY-6001",
                "verified_by": "a.aleks",
                "verified_at": "2026-10-02",
                "fields": {JUDGED: {"value": CAUSE}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    rubric = workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
    (gold / "calibrations" / f"{JUDGED}.json").write_text(
        json.dumps(
            {
                "judge_model": Model.model_id,
                "rubric_hash": text_hash(rubric),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _workspace(
    workspace: Path, monkeypatch, *, masked: bool = True, tracker: FakeTracker | None = None
) -> tuple[Model, FakeMasker]:
    """`PLAY-6001` to audit, `OPS-114` as reference, synced, and the model and masker served."""
    import dossier.cli.bootstrap as cli

    procedure = workspace / "inbox" / "procedures" / "OPS-114.md"
    procedure.parent.mkdir(parents=True, exist_ok=True)
    procedure.write_text(OPS_114, encoding="utf-8")
    (workspace / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    path = write_pipeline(
        workspace,
        name=PIPELINE,
        sources=[SOURCE_ID],
        reference=["procedures"],
        inputs={"extract": "[documents, reference]"},
    )
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        declaration = path.parent / "masking" / "cid.yaml"
        declaration.parent.mkdir()
        declaration.write_text(DECLARATION, encoding="utf-8")
    _gold(workspace)

    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
    )
    model = Model()
    masker = FakeMasker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    # The seam spec 021 adds beside `build_model_client`: the masker a
    # declaration names, built where every other port is (docs/architecture.md).
    monkeypatch.setattr(cli, "build_masker", lambda name: masker, raising=False)
    if tracker is not None:
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)

    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return model, masker


def _run_and_eval(workspace: Path, monkeypatch) -> None:
    ran = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    assert re.search(r"^run \S+", ran.output, re.MULTILINE), ran.output
    scored = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
    assert scored.exit_code == 0, scored.output


class TestAMaskedPipelineShowsNoModelClientData:
    """R21.1 — a masked pipeline's run and eval show no model a value its masker detects."""

    def test_neither_the_step_nor_the_judge_is_shown_a_canary(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where the canaries never reach the model.

        The step and the judge are both asked -- the judge through the eval's
        own road to the document's text -- and every prompt holds the
        placeholders where the converted text held the values.
        """
        model, masker = _workspace(workspace, monkeypatch)

        _run_and_eval(workspace, monkeypatch)

        assert model.judged, "the eval asked no judge, so it proves nothing about one"
        assert _held(model.prompts) == []
        assert masker.call_count > 0
        step = model.prompts[0]
        assert "[PERSON_1]" in step
        assert "[PERSON_2]" in step
        assert "[IBAN_CODE_1]" in step
        assert "[IBAN_CODE_1]" in model.judged[0]

    def test_the_reference_procedure_is_masked_as_a_document_is(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the procedure names a client too.

        `OPS-114` is context every call reading `reference` is shown whole
        (R3.18); `Hans Muster` in it is shown to the model no more than in
        the incident.
        """
        model, _ = _workspace(workspace, monkeypatch)

        _run_and_eval(workspace, monkeypatch)

        reading = [prompt for prompt in model.prompts if "OPS-114" in prompt]
        assert reading, "no call was shown the procedure"
        assert all("Hans Muster" not in prompt for prompt in reading)
        assert all("call [PERSON_1] first" in prompt for prompt in reading)

    def test_no_span_recorded_holds_a_canary(self, workspace: Path, monkeypatch):
        """Row 3: the one where a trace records what was sent.

        Under `capture: full` each span holds the prompt values and the reply.
        A masked run recorded nothing a model was not shown.
        """
        tracker = FakeTracker()
        _workspace(workspace, monkeypatch, tracker=tracker)

        _run_and_eval(workspace, monkeypatch)

        assert tracker.spans, "nothing was recorded, so the rule is vacuous"
        recorded = repr(tracker.runs) + repr(tracker.runless_traces)
        assert [value for value in CANARIES if value in recorded] == []
        assert "[IBAN_CODE_1]" in recorded

    def test_an_unmasked_pipeline_shows_the_converted_text(self, workspace: Path, monkeypatch):
        """Row 4, a counter-example: the one where nothing is declared.

        The same pipeline without `masking:` reads what it always read, and
        the masker is never asked.
        """
        model, masker = _workspace(workspace, monkeypatch, masked=False)

        _run_and_eval(workspace, monkeypatch)

        assert "Erika Mustermann" in model.prompts[0]
        assert "CH93 0076 2011 6238 5295 7" in model.prompts[0]
        assert "Erika Mustermann" in model.judged[0]
        assert masker.call_count == 0
