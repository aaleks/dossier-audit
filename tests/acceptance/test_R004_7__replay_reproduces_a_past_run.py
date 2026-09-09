"""R4.7 — `--replay` reproduces a past run byte-for-byte and touches no network.

Regardless of what `pipeline.yaml` says today.

The strongest form this promise takes is structural rather than asserted:
`application.run.replay` takes no model client. It cannot call one, cannot be
handed one, and has no parameter where one would go. A test can only observe that
no call happened; the signature makes it impossible.

These rows go through the CLI, because that is where a person replays a run and
because the path from `runs/<run_id>/manifest.json` back to reproduced artifacts
crosses the manifest, the ledger, the snapshot store, the converters and the
cache. Any one of them consulting today's configuration instead of the manifest
would break the rule while every unit test still passed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {"field": "summary", "value": "reviewed", "source": {
                    "document": document, "span": "Reopened"}}
            ],
        }
    )


@pytest.fixture
def completed(workspace: Path, monkeypatch) -> str:
    """A workspace with one finished run, and the run id it wrote.

    The model is replaced at the composition root, which is the seam R4.6 already
    asserts `--plan` never reaches. Here it *is* reached -- once per document --
    and then never again.
    """
    from tests.fakes import FakeModelClient

    import dossier.cli.main as cli

    write_pipeline(workspace, steps=["extract"])
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0

    keys = sorted(
        path.name for path in (workspace / "inbox" / "incidents").iterdir()
    )
    client = FakeModelClient(responses=[_answer(key) for key in keys])
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)

    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return sorted(path.name for path in (workspace / "runs").iterdir())[-1]


def _artifacts(workspace: Path) -> dict[str, bytes]:
    root = workspace / ".dossier" / "cache" / "stage"
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestAReplayReproducesTheRun:
    """R4.7 — the manifest is the only input."""

    def test_a_replay_completes_without_reaching_a_model(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """Example 1: the one where the network is stubbed to raise.

        `NoModelClient` fails at the call site, and the autouse `no_network`
        fixture makes a socket impossible. Neither is reached: `replay` takes no
        client at all.
        """
        from tests.fakes import NoModelClient

        import dossier.cli.main as cli

        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id: NoModelClient(), raising=False
        )
        before = _artifacts(workspace)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")

        assert result.exit_code == 0, result.output
        assert "no model calls" in result.output
        assert _artifacts(workspace) == before, "a replay writes no new artifact"
        # The counts, because "wrote nothing" and "reproduced nothing" are both
        # satisfied by a replay that did nothing at all -- which passed five of
        # these six rows before `/quality` found it.
        assert "3 artifact(s) reproduced" in result.output
        assert "extract: 3 artifact(s) from cache" in result.output

    def test_an_edited_pipeline_is_ignored(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """Example 2: the one where a step is added afterwards.

        The pipeline now has two steps. The replay reports one, because the
        manifest recorded one. A replay that read `pipeline.yaml` would look for
        an artifact the original run never wrote and fail -- loudly, but for
        entirely the wrong reason.
        """
        write_pipeline(
            workspace, steps=["extract", "enrich"], inputs={"enrich": "extract"}
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")

        assert result.exit_code == 0, result.output
        assert "extract: 3 artifact(s) from cache" in result.output
        assert "enrich" not in result.output

    def test_a_deleted_pipeline_is_ignored(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """Example 2, taken to its limit: the one where the config is gone.

        If the manifest is genuinely the only input, removing the file it came
        from changes nothing. This is the assertion that catches a replay quietly
        loading configuration "just to check".
        """
        (workspace / "pipelines" / PIPELINE / "pipeline.yaml").unlink()

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")

        assert result.exit_code == 0, result.output
        assert "3 artifact(s) reproduced" in result.output

    def test_the_manifests_model_is_the_one_used(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """Example 3: the one where the pin has since been changed.

        `pipeline.yaml` now names a different model. The replay reproduces the
        run under the model that produced it -- and would find no cached artifact
        if it had adopted today's pin, because the model identifier is part of
        every stage key (R5.3).
        """
        manifest = json.loads(
            (workspace / "runs" / completed / "manifest.json").read_text(encoding="utf-8")
        )
        write_pipeline(
            workspace, steps=["extract"], model="anthropic:claude-opus-4-1-20250805"
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")

        assert result.exit_code == 0, result.output
        assert "3 artifact(s) reproduced" in result.output
        assert manifest["plan"]["model"] == "anthropic:claude-sonnet-4-5-20250929"

    def test_a_missing_snapshot_is_named_and_nothing_is_substituted(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """Counter-example (row 4): the one where a replay is allowed to fail.

        A snapshot has gone from the store. The replay stops and names what is
        missing. What it must never do is convert some other document and present
        the result as the original run -- so the exit is non-zero and no artifact
        is reported.
        """
        store = workspace / ".dossier" / "snapshots"
        for snapshot in store.rglob("*"):
            if snapshot.is_file():
                snapshot.unlink()

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")

        assert result.exit_code == 2
        assert "no model calls" not in result.output
        # Row 4 says "a clear error naming the missing hash". It used to name a
        # stage cache key instead -- and the stage artifact was still on disk, so
        # the message sent the reader to a directory holding exactly what it said
        # was absent.
        assert "no snapshot for" in result.output

    def test_a_missing_manifest_is_refused(self, workspace: Path, monkeypatch, completed: str):
        """The one where the run directory does not exist.

        Named rather than reported as an empty replay, which would be a run that
        reproduced nothing while claiming success.
        """
        result = _cli(
            workspace, monkeypatch, "run", PIPELINE, "--replay", "runs/20260101T000000Z-zzzz"
        )

        assert result.exit_code == 2
        assert "manifest" in result.output


class TestAReplayIsPinnedToTheConvertersItUsed:
    """R4.7 row 1 — "byte-identical" has to survive the tools moving on.

    Spec 004's manifest section requires converter versions to be recorded, and
    they were not. `/quality` found the consequence: `_replay` re-converted with
    whatever `installed_converters()` returns *today*, so raising a converter
    version broke the replay of every run ever made — and broke it as a missing
    cache artifact, which names neither the converter nor the version and reads
    like a corrupted cache.

    A past audit is defended by what it actually read (R4.9). That has to include
    the tool that read it.
    """

    def test_raising_a_converter_version_does_not_break_a_past_replay(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """The one where the converter improved after the run.

        The artifact this run was built from was produced by `markdown-text`
        1.0.0. Version 1.1.0 may well produce different text — that is why a
        version is raised — but this run did not read that text, and replaying it
        must not pretend otherwise.
        """
        from dossier.infrastructure.converters.markdown_text import MarkdownTextConverter

        # Output *and* version, because a version is raised precisely when output
        # could change. Bumping the number alone on a passthrough converter
        # changes no bytes and so proves nothing.
        monkeypatch.setattr(MarkdownTextConverter, "version", "1.1.0")
        monkeypatch.setattr(
            MarkdownTextConverter,
            "convert",
            lambda self, payload, options: b"# better extraction\n" + payload,
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")

        assert result.exit_code == 0, result.output
        assert "3 artifact(s) reproduced" in result.output

    def test_the_manifest_records_the_converters_the_run_used(
        self, workspace: Path, monkeypatch, completed: str
    ):
        """Spec 004: the manifest holds converter versions.

        Recorded so the run is reproducible *without* the installed packages
        agreeing — which is the difference between a manifest that describes a
        run and one that merely describes a pipeline.
        """
        manifest = json.loads(
            (workspace / "runs" / completed / "manifest.json").read_text(encoding="utf-8")
        )

        converters = manifest["plan"]["converters"]
        assert {c["id"] for c in converters} == {"markdown-text"}
        assert {c["version"] for c in converters} == {"1.0.0"}
