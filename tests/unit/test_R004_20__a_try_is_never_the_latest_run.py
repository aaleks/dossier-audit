"""R4.20 — a try writes no manifest under `runs/`, so the latest run is still
the latest full run.

`dossier eval` scores the latest run, `--plan` compares against it, and a run
warns when the source has moved since it (R4.9 row 4). Every one of them finds
that run through `latest_manifest` over `runs/`, so that is what is read here:
a try that left a manifest there would be the run each of them found.

Run through `execute`, whose `tried` is what `--doc` names. Then row 2 through
the CLI as well: `latest_manifest` is what every reader calls, and a reader
that stopped calling it would pass the rows above and still be fooled.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for, write_pipeline
from tests.scoring_example import FIELDS, ISSUES, abstains

from dossier.application.plan import latest_manifest
from dossier.application.run import RunInputs, execute
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig

PIPELINE = "incident-audit"
FULL_RUN = "20260806T142203Z-4f1a"
TRY = "20260929T100000Z-1a2b"
LATER_RUN = "20260930T090000Z-bbbb"


def _execute(workspace: Path, run_id: str, *, tried: tuple[str, ...] | None = None) -> None:
    """`extract` per_file over the four incidents, answered whatever is asked."""
    from dossier.infrastructure.cache import ArtifactCache

    execute(
        RunInputs(
            pipeline=PipelineConfig(
                name=PIPELINE,
                sources=["incidents-jira"],
                model="anthropic:claude-sonnet-4-5-20250929",
                steps=[
                    StepConfig(
                        id="extract",
                        prompt="prompts/extract.md",
                        input="documents",
                        mode="per_file",
                    )
                ],
            ),
            pipeline_hash="6e0d4b27" * 8,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
            documents={key: sha256(text.encode()).hexdigest() for key, text in ISSUES.items()},
            document_text=ISSUES,
        ),
        workspace=workspace,
        model=FakeModelClient(
            responses=[json.dumps({"document": key, "fields": []}) for key in sorted(ISSUES)]
        ),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
        dossier_version="0.1.0",
        tried=tried,
    )


def _runs(workspace: Path) -> list[str]:
    return sorted(path.name for path in (workspace / "runs").iterdir())


class TestATryIsNeverTheLatestRun:
    """R4.20 — a try writes no manifest under `runs/`."""

    def test_the_full_run_before_a_try_is_still_the_latest(self, tmp_path: Path):
        """Rows 1 and 2 — the one where eval, --plan and the warning all find the full run.

        The try is later by its id, so a manifest of its own under `runs/`
        would sort last and be the one every reader found.
        """
        _execute(tmp_path, FULL_RUN)

        _execute(tmp_path, TRY, tried=("INC-4821",))

        assert _runs(tmp_path) == [FULL_RUN]
        assert latest_manifest(tmp_path / "runs", PIPELINE)[1] == FULL_RUN

    def test_a_full_run_after_a_try_is_the_latest(self, tmp_path: Path):
        """Row 3, counter-example — the one where a run follows the try, as every run is."""
        _execute(tmp_path, FULL_RUN)
        _execute(tmp_path, TRY, tried=("INC-4821",))

        _execute(tmp_path, LATER_RUN)

        assert _runs(tmp_path) == [FULL_RUN, LATER_RUN]
        assert latest_manifest(tmp_path / "runs", PIPELINE)[1] == LATER_RUN


class Model:
    """Answers every call with nothing extracted."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        (document,) = re.findall(r'<document key="([^"]+)">', prompt)
        return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


class TestPlanStillReadsTheFullRun:
    """R4.20 row 2, through the CLI: `--plan` after a try."""

    def test_a_plan_after_a_try_compares_against_the_full_run(
        self, workspace: Path, monkeypatch
    ):
        """Row 2 — the one where the plan is asked after the try, and names the run.

        The incidents are markdown in a folder source, so their keys carry the
        extension (`INC-4821.md`), as R3.17's do.
        """
        import dossier.cli.bootstrap as cli

        for name in ("INC-4821", "INC-4822"):
            path = workspace / "inbox" / "tickets" / f"{name}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(ISSUES[name], encoding="utf-8")
        (workspace / "sources.yaml").write_text(
            "sources:\n  - id: tickets\n    type: folder\n    path: inbox/tickets/\n",
            encoding="utf-8",
        )
        write_pipeline(workspace, name=PIPELINE, sources=["tickets"])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
        # The run and the try start within one second, so their ids differ only
        # in the random suffix, and the try's could sort first by chance. Pinned
        # so it sorts last: the case where a manifest of its own would win.
        suffixes = iter(["0000", "ffff"])
        monkeypatch.setattr("dossier.cli.run.token_hex", lambda n: next(suffixes))
        for args in (("sync", PIPELINE), ("run", PIPELINE)):
            assert _cli(workspace, monkeypatch, *args).exit_code == 0
        (full_run,) = _runs(workspace)
        tried = _cli(workspace, monkeypatch, "run", PIPELINE, "--doc", "INC-4821.md")
        assert tried.exit_code == 0, tried.output

        plan = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert plan.exit_code == 0, plan.output
        assert f"compared against {full_run}" in plan.output, plan.output
