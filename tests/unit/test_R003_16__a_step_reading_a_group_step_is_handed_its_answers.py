"""R3.16 — what a step reading a `per_group` step's output is handed.

R3.16 refuses, at load time, every reader of a group step's output but a
`per_group` or `aggregate` step. That is proved by the rule's other test. This
one proves what the readers it admits are then handed. A group step files its
answers under the group, `extract/ACME-2024.json`, and a reader that looked them
up under the group's members, as it looks up a `per_file` step's, found nothing:
`{{extract}}` rendered empty in every call, with a run that reported success.
Playground exercise 16 found it live, with an input hash that was the SHA-256 of
an empty string.

Run through `execute`, because what a call is handed is a fact about the run. A
replay recomposes each key from the same values (R4.14), so it is here too. The
model is a fake that records what each call was shown (R0.1).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import RunInputs, execute, replay
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
CONTRACTS = {
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call, and remembers each prompt, by the step that sent it."""

    model_id = MODEL

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        self.prompts.append(prompt)
        shown = SHOWN.findall(prompt)
        return json.dumps({"document": shown[0] if shown else "", "fields": []})

    def shown(self, section: str) -> list[list[str]]:
        """The keys each call's `<section>` held, for the calls that had one."""
        within = re.compile(rf"<{section}>(.*?)</{section}>", re.DOTALL)
        return [
            SHOWN.findall(held.group(1))
            for prompt in self.prompts
            if (held := within.search(prompt))
        ]


def _run(tmp_path: Path, model: Model, *steps: tuple[str, str, list[str]]):
    """`(id, mode, inputs)` steps over `CONTRACTS`, in order; the run's report."""
    return execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="contract-renewal",
                sources=["contracts"],
                model=MODEL,
                steps=[
                    StepConfig(id=step, prompt=f"prompts/{step}.md", input=inputs, mode=mode)
                    for step, mode, inputs in steps
                ],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={step: SCHEMA for step, _, _ in steps},
            prompts={step: prompt_for(inputs) for step, _, inputs in steps},
            documents={
                key: sha256(text.encode()).hexdigest() for key, text in CONTRACTS.items()
            },
            document_text=CONTRACTS,
        ),
        workspace=tmp_path,
        model=model,
        cache=ArtifactCache(tmp_path, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
    )


EXTRACT_PER_GROUP = ("extract", "per_group", ["documents"])
VERIFY = ("verify", "per_group", ["documents", "extract"])


class TestAStepReadingAGroupStepIsHandedItsAnswers:
    """R3.16 — each admitted reader of a group step is handed the group's answer."""

    def test_a_group_step_is_handed_its_own_groups_answer(self, tmp_path: Path):
        """Row 1: the one where `verify` checks each contract's extraction.

        ACME's call holds its two documents and `extract/ACME-2024.json`, under
        the group's name, since that is what the answer is about. GLOBEX's holds
        GLOBEX's, and never ACME's.
        """
        model = Model()
        _run(tmp_path, model, EXTRACT_PER_GROUP, VERIFY)

        assert model.shown("extract") == [["ACME-2024"], ["GLOBEX-2023"]]
        # The answer itself, not only a wrapper named for it. The calls go
        # extract ACME, extract GLOBEX, then verify ACME.
        assert '"document": "ACME-2024"' in model.prompts[2]

    def test_an_aggregate_step_is_handed_every_groups_answer(self, tmp_path: Path):
        """Row 2: the one where `report` reads every contract's answer.

        One call, holding each group's answer under its group's name.
        """
        model = Model()
        _run(tmp_path, model, EXTRACT_PER_GROUP, ("report", "aggregate", ["extract"]))

        assert model.shown("extract") == [["ACME-2024", "GLOBEX-2023"]]

    def test_a_group_step_reading_a_per_file_step_is_handed_its_members_answers(
        self, tmp_path: Path
    ):
        """Row 4: counter-example -- the one where `combine` reads `per_file` answers.

        A `per_file` step files each answer under its document's key, so a
        group's call holds its members' answers, each under the member's key,
        and nothing under the group's name: no answer is filed there.
        """
        model = Model()
        _run(
            tmp_path,
            model,
            ("extract", "per_file", ["documents"]),
            ("combine", "per_group", ["extract"]),
        )

        assert model.shown("extract") == [
            ["ACME-2024/amendment-3.pdf", "ACME-2024/master.pdf"],
            ["GLOBEX-2023/master.pdf"],
        ]

    def test_a_replay_is_handed_what_the_run_was(self, tmp_path: Path):
        """The one where a replay recomposes `verify`'s keys from the same answers.

        A replay that composed `{{extract}}` differently from the run would look
        for a key the run never wrote, and stop (R4.14). Served from cache in
        full, with no model to ask, it composed the same.
        """
        report = _run(tmp_path, Model(), EXTRACT_PER_GROUP, VERIFY)

        replayed = replay(
            manifest=Manifest.read(report.manifest_path),
            document_text=CONTRACTS,
            cache=ArtifactCache(tmp_path, namespace="stage"),
        )

        assert [len(step.served_from_cache) for step in replayed.steps] == [2, 2]
