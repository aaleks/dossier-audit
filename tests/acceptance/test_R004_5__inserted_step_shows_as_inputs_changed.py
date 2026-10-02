"""R4.5 — reordering or inserting a step changes a resolved input list, and `--plan`
shows it before anything runs.

The trap this closes: an insertion looks local in the YAML and silently re-points
every relative reference below it. Someone adding `enrich` between `extract` and
`verify` has, without touching `verify` at all, changed what `verify` reads --
and the only place that is visible before a bill arrives is here.

The previous run's manifest is written with the production model rather than a
literal, so this test cannot pass against a format `run` does not actually
produce.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.pipelines import PROVIDERS, write_pipeline

from dossier.application.manifest import Manifest
from dossier.application.run import key_hashes, write_failures
from dossier.config.load import load_output_schemas, load_pipeline
from dossier.domain.hashing import content_hash
from dossier.domain.resolution import resolve

PIPELINE = "incident-audit"
EARLIER_RUN = "20260806T142203Z-4f1a"


def _plan(workspace: Path, monkeypatch):
    """`dossier run incident-audit --plan`, with the workspace as the cwd."""
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    result = CliRunner().invoke(app, ["run", PIPELINE, "--plan"])
    assert result.exit_code == 0, result.output
    return result.output


def _record_a_run(workspace: Path) -> None:
    """Freeze the pipeline as it stands into `runs/`, as a real run would.

    Written through `Manifest`, which is what `application.run` writes, so the
    diff below is compared against the real thing rather than against a shape
    invented by this test.
    """
    path = workspace / "pipelines" / PIPELINE / "pipeline.yaml"
    config = load_pipeline(path, providers=PROVIDERS)
    # Keyed as a run keys it: a manifest without the prompt and declaration
    # hashes is a shape no run writes, and a plan compared against one would
    # report every prompt as changed (R4.12).
    prompt_hashes, schema_hashes = key_hashes(
        config,
        prompts={
            step.id: (path.parent / step.prompt).read_text(encoding="utf-8")
            for step in config.steps
        },
        schemas=load_output_schemas(config, path),
    )
    plan = resolve(
        pipeline=config,
        pipeline_hash=content_hash(path.read_bytes()),
        documents={},
        prompt_hashes=prompt_hashes,
        schema_hashes=schema_hashes,
    )
    Manifest(
        run_id=EARLIER_RUN,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        plan=plan,
    ).write(workspace / "runs")
    # And finished, as a run that ended writes it: a plan compares only against
    # a run that wrote `failures.json`, `[]` for one that failed nothing (R4.31).
    write_failures(workspace / "runs" / EARLIER_RUN, [])


class TestAnInsertedStepShowsUp:
    """R4.5 — the change that looks local and is not."""

    def test_inserting_a_step_repoints_the_one_below_it(self, workspace: Path, monkeypatch):
        """Example 1: the one where `verify` changes without being edited."""
        write_pipeline(
            workspace,
            steps=["extract", "verify", "report"],
            inputs={"verify": "[documents, previous]", "report": "previous"},
        )
        _record_a_run(workspace)

        write_pipeline(
            workspace,
            steps=["extract", "enrich", "verify", "report"],
            inputs={"verify": "[documents, previous]", "report": "previous"},
        )
        output = _plan(workspace, monkeypatch)

        assert "verify: inputs changed" in output
        assert "was: [documents, extract]" in output
        assert "now: [documents, enrich]" in output

    def test_the_step_below_that_reports_upstream_changed(self, workspace: Path, monkeypatch):
        """Example 2: the one where `report` re-runs without changing at all.

        `report` still reads `verify` and still reads the same prompt. It re-runs
        because what `verify` will produce is no longer what it produced, which
        is the cascade R5.2 describes made visible before it costs anything.
        """
        write_pipeline(
            workspace,
            steps=["extract", "verify", "report"],
            inputs={"verify": "[documents, previous]", "report": "previous"},
        )
        _record_a_run(workspace)

        write_pipeline(
            workspace,
            steps=["extract", "enrich", "verify", "report"],
            inputs={"verify": "[documents, previous]", "report": "previous"},
        )
        output = _plan(workspace, monkeypatch)

        assert "report: upstream changed" in output
        assert "enrich: new" in output
        assert "extract: cached" in output, "nothing above the insertion is affected"

    def test_swapping_two_steps_changes_a_resolved_input_list(
        self, workspace: Path, monkeypatch
    ):
        """Example 3: the one where nothing was added and the graph still moved.

        `extract` and `verify` both read `documents`, so swapping them looks like
        pure cosmetics. `report` reads `previous`, and `previous` now means
        something else.
        """
        write_pipeline(
            workspace,
            steps=["extract", "verify", "report"],
            inputs={"verify": "documents", "report": "previous"},
        )
        _record_a_run(workspace)

        write_pipeline(
            workspace,
            steps=["verify", "extract", "report"],
            inputs={"verify": "documents", "report": "previous"},
        )
        output = _plan(workspace, monkeypatch)

        assert "report: inputs changed" in output
        assert "was: [verify]" in output
        assert "now: [extract]" in output

    def test_a_comment_changes_the_hash_and_nothing_else(self, workspace: Path, monkeypatch):
        """Counter-example (row 4): the one where the file changed and the run did not.

        This is the row that stops `--plan` being implemented as "did
        pipeline.yaml change?". The hash moves, because the hash identifies the
        file as written. No resolved input list moves, so every step is still
        cached -- and a plan that re-ran everything here would make the command
        useless exactly when someone is tidying up.
        """
        write_pipeline(
            workspace,
            steps=["extract", "verify", "report"],
            inputs={"verify": "[documents, previous]", "report": "previous"},
        )
        _record_a_run(workspace)

        path = workspace / "pipelines" / PIPELINE / "pipeline.yaml"
        before = content_hash(path.read_bytes())
        path.write_text(
            "# Reviewed 2026-09-08; no behaviour change.\n" + path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        output = _plan(workspace, monkeypatch)

        assert content_hash(path.read_bytes()) != before, "the file really did change"
        for step in ("extract", "verify", "report"):
            assert f"{step}: cached" in output
        assert "inputs changed" not in output
        assert "0 of 3 step(s) would run" in output
