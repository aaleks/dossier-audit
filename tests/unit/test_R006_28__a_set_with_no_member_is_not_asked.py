"""R6.28 — a step reading a set is not asked when no member of the set has what
it reads.

R6.13 row 4: an `aggregate` step runs over the documents that did produce
output, and a `per_group` step reads its group's the same way (R3.15). When
none did, it was asked anyway, about `<extract></extract>`: a call about
nothing, cached under the key of nothing. The cause is already reported, once,
at the step every member failed, so this is a skip and not a failure.

Run through `execute`, with a model that fails `extract` for the documents
named to fail -- not JSON, twice, so the retry fails too (R6.2) -- answers it
for the others, and answers a step with no `output` in prose. It keeps what
each call was about, so the calls are **counted** per step.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.run import RunInputs, RunReport, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
RUN_ID = "20260929T140000Z-0a0a"
INCIDENTS = {
    "INC-4821": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
CONTRACTS = {
    "ACME-2024/amendment-3.pdf": "Amendment 3 extends the term to 2027-03-31.",
    "ACME-2024/master.pdf": "Liability is capped at EUR 2,000,000.",
    "GLOBEX-2023/master.pdf": "The term ends 2026-12-31.",
}
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """`extract` fails for the documents in `failing`; a prose step answers in prose."""

    model_id = MODEL

    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.calls: list[tuple[str, list[str]]] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        shown = SHOWN.findall(prompt)
        step = "extract" if schema is not None else "set"
        self.calls.append((step, shown))
        if schema is None:
            return "Summary of what was read."
        if shown[0] in self.failing:
            return "not JSON at all"
        return json.dumps({"document": shown[0], "fields": []})

    def asked(self, step: str) -> list[list[str]]:
        return [shown for called, shown in self.calls if called == step]


def _run(workspace: Path, text: dict[str, str], model: Model, *, mode: str) -> RunReport:
    """`extract` per_file, then a set step reading it, `report` or `combine`."""
    from dossier.infrastructure.cache import ArtifactCache

    reader = "report" if mode == "aggregate" else "combine"
    return execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit",
                sources=["incidents-jira"],
                model=MODEL,
                steps=[
                    StepConfig(
                        id="extract",
                        prompt="prompts/extract.md",
                        input="documents",
                        mode="per_file",
                        output="schemas/incident.yaml",
                    ),
                    StepConfig(
                        id=reader, prompt=f"prompts/{reader}.md", input="extract", mode=mode
                    ),
                ],
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={"extract": SCHEMA, reader: None},
            prompts={"extract": prompt_for(["documents"]), reader: prompt_for(["extract"])},
            documents={key: sha256(body.encode()).hexdigest() for key, body in text.items()},
            document_text=text,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=datetime(2026, 9, 29, 14, 0, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _written(workspace: Path, step: str) -> list[str]:
    folder = workspace / "runs" / RUN_ID / step
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


class TestASetWithNoMemberIsNotAsked:
    """R6.28 — a set step with no member holding its input is skipped, not asked."""

    def test_a_report_over_incidents_that_all_failed_is_not_asked(self, tmp_path: Path):
        """Row 1 — the one where every incident failed `extract`."""
        model = Model(failing={"INC-4821", "INC-4822"})

        report = _run(tmp_path, INCIDENTS, model, mode="aggregate")

        assert model.asked("set") == [], "the report was asked about nothing"
        assert _written(tmp_path, "report") == []
        assert report.failed == [("extract", "INC-4821"), ("extract", "INC-4822")]

    def test_a_contract_whose_members_all_failed_is_not_asked(self, tmp_path: Path):
        """Row 2 — the one where ACME-2024 failed and GLOBEX-2023 did not.

        One call for the group that has answers. ACME-2024 is not asked, and is
        not a second failure: its members are each listed once, under `extract`.
        """
        model = Model(failing={"ACME-2024/amendment-3.pdf", "ACME-2024/master.pdf"})

        report = _run(tmp_path, CONTRACTS, model, mode="per_group")

        assert model.asked("set") == [["GLOBEX-2023/master.pdf"]]
        assert report.failed == [
            ("extract", "ACME-2024/amendment-3.pdf"),
            ("extract", "ACME-2024/master.pdf"),
        ]

    def test_a_report_with_one_incident_that_worked_is_asked(self, tmp_path: Path):
        """Row 3, counter-example — the one where a member is enough (R6.13 row 4)."""
        model = Model(failing={"INC-4822"})

        report = _run(tmp_path, INCIDENTS, model, mode="aggregate")

        assert model.asked("set") == [["INC-4821"]]
        assert report.failed == [("extract", "INC-4822")]
