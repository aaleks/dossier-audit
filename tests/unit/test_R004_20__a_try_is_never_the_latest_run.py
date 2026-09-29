"""R4.20 — a try writes no manifest under `runs/`, so the latest run is still
the latest full run.

`dossier eval` scores the latest run, `--plan` compares against it, and a run
warns when the source has moved since it (R4.9 row 4). Every one of them finds
that run through `latest_manifest` over `runs/`, so that is what is read here:
a try that left a manifest there would be the run each of them found.

Run through `execute`, whose `tried` is what `--doc` names.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

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
