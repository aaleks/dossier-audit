"""R4.6 — `--plan` performs no model calls, writes no outputs and leaves the cache untouched.

`--plan` is the command you run when you do not trust what is about to happen.
That only works if running it is free and changes nothing: a plan that warmed a
cache, or asked a model what it thought, would answer a slightly different
question than the run it claims to preview.

The rule is a claim about *absence*, which is the hardest kind to test and the
easiest to pass by accident. A command that crashed immediately would write no
outputs and make no calls. So each row here pairs the absence with evidence that
the work was really considered: the plan names every step, and says of each one
what would happen to it.

No single component satisfies this. Config loading must read the pipeline, the
domain must resolve its references and pin the snapshots the ledger holds, the
application must diff against the last manifest, and the CLI must print the
result -- all without the composition root ever reaching for a model.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """A workspace whose documents are already held.

    `--plan` pins the snapshots a run would read, so there has to be something
    to pin. Syncing first is what a user does, and it keeps this test about
    planning rather than about fetching.
    """
    _run(workspace, monkeypatch, "sync", PIPELINE)
    return workspace


@pytest.fixture
def model_calls(monkeypatch) -> list[str]:
    """Every model client the composition root asked for, and every call made.

    `--plan` should never reach this. Recording the *request for a client* as
    well as the calls is deliberate: a plan that built a client and then made no
    call has still loaded a vendor SDK and read a credential, and the point of
    the rule is that planning is free.
    """
    from tests.fakes import FakeModelClient

    import dossier.cli.main as cli

    # One list for both events, so a failure message says which of them happened.
    record: list = []
    client = FakeModelClient(responses=[], calls=record)

    def build(model_id: str):
        record.append(f"built a client for {model_id}")
        return client

    monkeypatch.setattr(cli, "build_model_client", build, raising=False)
    return record


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _tree(root: Path) -> dict[str, tuple[bytes, int]]:
    """Content and modification time of every file under a directory.

    Content alone would miss a rewrite with identical bytes, which is still a
    write and still breaks the promise that planning changes nothing.
    """
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestPlanIsReadOnly:
    """R4.6 — `--plan` reports work; it does not do it."""

    def test_planning_asks_for_no_model(self, synced: Path, monkeypatch, model_calls):
        """Example 1: the one where the model client is never even built."""
        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert model_calls == []

    def test_planning_still_names_every_step(self, synced: Path, monkeypatch, model_calls):
        """Example 1, the other half: the one proving it did the thinking.

        Without this, a `run` sub-command that raised on the first line would
        satisfy every absence this rule asserts.
        """
        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert "extract" in result.output

    def test_planning_writes_no_run_directory(self, synced: Path, monkeypatch, model_calls):
        """Example 1: the one where no `runs/<id>/` appears (R4.1 example 2)."""
        before = _tree(synced / "runs")

        _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert _tree(synced / "runs") == before

    def test_planning_leaves_the_cache_byte_identical(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Example 2: the one asserted on modification times as well as content."""
        cache = synced / ".dossier"
        before = _tree(cache)

        _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert _tree(cache) == before

    def test_a_pipeline_where_everything_would_rerun_still_does_nothing(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Example 3: the one where there is the most work to decline to do.

        Three steps, none of them ever run, so every one of them is outstanding.
        A plan that quietly did the work it found would show it here first.
        """
        write_pipeline(
            synced,
            steps=["extract", "verify", "report"],
            inputs={"verify": "[documents, extract]", "report": "verify"},
        )
        before = _tree(synced / ".dossier")

        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert model_calls == []
        assert _tree(synced / ".dossier") == before
        assert _tree(synced / "runs") == {}
        for step in ("extract", "verify", "report"):
            assert step in result.output

    def test_reading_the_previous_manifest_is_permitted(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Counter-example (row 4): the one where a read is not a write.

        The rule forbids calling and writing, not reading. A second `--plan`
        has a manifest to diff against and must still make no calls and change
        nothing -- but it is allowed to open what the first one left.
        """
        _run(synced, monkeypatch, "run", PIPELINE, "--plan")
        before = _tree(synced / ".dossier")

        second = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert second.exit_code == 0, second.output
        assert model_calls == []
        assert _tree(synced / ".dossier") == before
