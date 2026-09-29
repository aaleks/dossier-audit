"""R4.28 — a replay reproduces each failure the run recorded, and asks for no
entry for it.

What a run recorded as failed (R4.27), a replay fails the same way, with the
recorded reason. It never had an entry, and looking for one stopped the replay
on a failure the run reported rather than lost. The steps after it skip it as
the run did (R6.13). A missing entry the run did not record as failed still
stops the replay: that is a lost entry, and reproducing it as a failure would be
the substitution R4.7 row 4 forbids.

Row 1 through the CLI, where the replay prints what it reproduced. The incidents
are markdown in a folder source there, so their keys carry the extension
(`INC-4822.md`), as R3.17's do. The rest through `execute` and `replay`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.fakes import FakeModelClient, NoModelClient
from tests.pipelines import prompt_for, write_pipeline

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.run import (
    MissingFromReplay,
    RunInputs,
    RunReport,
    execute,
    recorded_failures,
    replay,
)
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
RUN_ID = "20260929T180000Z-0e0e"
NOT_JSON = "not JSON at all"
REASON = "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
TEXT = {
    "INC-4821": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = [
    (f"page-00{n}.png", ImagePart(media_type=PART_TYPE, data=f"INC-4830 page {n}".encode()))
    for n in (1, 2, 3)
]


def _answer(document: str) -> str:
    return json.dumps({"document": document, "fields": []})


def _step(step: str, source: str, *, mode: str = "per_file") -> StepConfig:
    return StepConfig(
        id=step, prompt=f"prompts/{step}.md", input=source, mode=mode, output="s.yaml"
    )


def _execute(
    workspace: Path, replies, *, steps=None, text=TEXT, parts=None, run_id=RUN_ID
) -> None:
    from dossier.infrastructure.cache import ArtifactCache

    steps = steps or [_step("extract", "documents")]
    execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit", sources=["incidents-jira"], model=MODEL, steps=steps
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={step.id: SCHEMA for step in steps},
            prompts={step.id: prompt_for([step.input]) for step in steps},
            documents={key: sha256(key.encode()).hexdigest() for key in text},
            document_text=text,
            document_content={"markdown": text},
            document_parts=parts,
        ),
        workspace=workspace,
        model=FakeModelClient(responses=replies),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 9, 29, 18, 0, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _replay(workspace: Path, *, text=TEXT, parts=None, recorded: bool = True) -> RunReport:
    from dossier.infrastructure.cache import ArtifactCache

    run = workspace / "runs" / RUN_ID
    return replay(
        manifest=Manifest.read(run / MANIFEST_NAME),
        document_text=text,
        document_parts=parts,
        cache=ArtifactCache(workspace, namespace="stage"),
        failures=recorded_failures(run) if recorded else None,
    )


def _results(report: RunReport, step: str) -> dict:
    (done,) = [done for done in report.steps if done.step == step]
    return {result.document: result for result in done.results}


class TestAReplayReproducesARecordedFailure:
    """R4.28 — a recorded failure is reproduced, and no entry is asked for it."""

    def test_the_replay_prints_the_failure_the_run_printed(self, workspace: Path, monkeypatch):
        """Row 1 — the one where INC-4822 failed and the run replays, exit 0."""
        import dossier.cli.bootstrap as cli

        inbox = workspace / "inbox" / "tickets"
        inbox.mkdir(parents=True)
        for key, body in TEXT.items():
            (inbox / f"{key}.md").write_text(body, encoding="utf-8")
        (workspace / "sources.yaml").write_text(
            "sources:\n  - id: tickets\n    type: folder\n    path: inbox/tickets/\n",
            encoding="utf-8",
        )
        write_pipeline(workspace, name="incident-audit", sources=["tickets"])
        model = FakeModelClient(responses=[_answer("INC-4821.md"), NOT_JSON, NOT_JSON])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
        assert _cli(workspace, monkeypatch, "sync", "incident-audit").exit_code == 0
        assert _cli(workspace, monkeypatch, "run", "incident-audit").exit_code == 1
        (run_id,) = sorted(path.name for path in (workspace / "runs").iterdir())
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(workspace, monkeypatch, "run", "--replay", f"runs/{run_id}/")

        assert result.exit_code == 0, result.output
        assert "1 artifact(s) reproduced" in result.output, result.output
        line = f"    extract failed on INC-4822.md: {REASON}"
        assert line in result.stderr.splitlines(), result.stderr

    def test_a_later_step_skips_the_failed_document_as_the_run_did(self, tmp_path: Path):
        """Row 2 — the one where `verify` reads `extract`, which INC-4822 failed (R6.13)."""
        steps = [_step("extract", "documents"), _step("verify", "extract")]
        _execute(
            tmp_path,
            [_answer("INC-4821"), NOT_JSON, NOT_JSON, _answer("INC-4821")],
            steps=steps,
        )

        replayed = _replay(tmp_path)

        assert _results(replayed, "extract")["INC-4822"].error == REASON
        assert list(_results(replayed, "verify")) == ["INC-4821"]
        assert replayed.failed == [("extract", "INC-4822")]

    def test_a_failed_page_is_reproduced_beside_the_pages_that_were_served(
        self, tmp_path: Path
    ):
        """Row 3 — the one where page 2 of three was recorded as failed."""
        page = _answer(POSTMORTEM)
        text = {POSTMORTEM: "SEV-1 | Checkout TLS expiry"}
        parts = {"page_images": {POSTMORTEM: PAGES}}
        _execute(
            tmp_path,
            [page, NOT_JSON, NOT_JSON, page],
            steps=[_step("extract", "documents@page_images", mode="per_part")],
            text=text,
            parts=parts,
        )

        replayed = _replay(tmp_path, text=text, parts=parts)

        (done,) = replayed.steps
        assert _results(replayed, "extract")[POSTMORTEM].error == f"page-002.png: {REASON}"
        assert [page.failed for page in done.parts] == [False, True, False]

    def test_an_entry_lost_since_the_run_still_stops_the_replay(self, tmp_path: Path):
        """Row 4, counter-example — the one whose cache entry was deleted, not failed."""
        _execute(tmp_path, [_answer("INC-4821"), NOT_JSON, NOT_JSON])
        record = tmp_path / "runs" / RUN_ID / "extract" / "INC-4821.meta.json"
        key = json.loads(record.read_text(encoding="utf-8"))["cache_key"]
        for held in (tmp_path / ".dossier" / "cache" / "stage").rglob(f"*{key}*"):
            held.unlink()

        with pytest.raises(MissingFromReplay, match="INC-4821"):
            _replay(tmp_path)

    def test_a_run_from_before_the_record_stops_as_it_did(self, tmp_path: Path):
        """Row 5, counter-example — the one with no `failures.json` to read."""
        _execute(tmp_path, [_answer("INC-4821"), NOT_JSON, NOT_JSON])

        with pytest.raises(MissingFromReplay, match="INC-4822"):
            _replay(tmp_path, recorded=False)

    def test_a_later_runs_answer_does_not_rewrite_the_failure(self, tmp_path: Path):
        """Row 6 — the one answered by a second run since, under the same key.

        The only row in which there is an entry to find. A replay that looked the
        cache up before its record passed every other row, and would serve the
        second run's answer here as the first run's (R4.7).
        """
        from dossier.infrastructure.cache import ArtifactCache

        _execute(tmp_path, [_answer("INC-4821"), NOT_JSON, NOT_JSON])
        # The same pipeline again: INC-4821 served from the cache, INC-4822 asked
        # afresh and answered this time.
        later = "20260929T190000Z-0f0f"
        _execute(tmp_path, [_answer("INC-4822")], run_id=later)
        served = replay(
            manifest=Manifest.read(tmp_path / "runs" / later / MANIFEST_NAME),
            document_text=TEXT,
            cache=ArtifactCache(tmp_path, namespace="stage"),
            failures=recorded_failures(tmp_path / "runs" / later),
        )
        assert not _results(served, "extract")["INC-4822"].failed, "nothing to find"

        replayed = _replay(tmp_path)

        assert _results(replayed, "extract")["INC-4822"].error == REASON
        assert replayed.failed == [("extract", "INC-4822")]
