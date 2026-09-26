"""R4.13 — a step naming a kind no source in its set produces stops the run.

R3.11 lets a step name a kind. This is what happens when it names one nothing
will produce, and it is proved through the CLI because the whole value of the
rule is *when* the reader hears about it: before a model call, before a run
directory, from the configuration alone.

The failure is deliberately resolution's shape rather than conversion's (R8.5).
The two have different fixes. R8.5 says "nothing converts this pair" and wants an
installation; this says "your pipeline asked a source for something it was never
told to make" and wants a line in `sources.yaml`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _sources(workspace: Path, convert: str | None) -> None:
    """Rewrite `sources.yaml`, with or without a `convert:` list."""
    declared = f"    convert: [{convert}]\n" if convert else ""
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: incidents-manual\n"
        "    type: folder\n"
        "    path: inbox/incidents/\n" + declared,
        encoding="utf-8",
    )


@pytest.fixture
def asks_for_page_images(workspace: Path) -> Path:
    """A pipeline whose one step reads `documents@page_images`."""
    write_pipeline(
        workspace,
        steps=["describe"],
        inputs={"describe": "documents@page_images"},
        outputs={"describe": None},
    )
    return workspace


class TestAKindNoSourceProducesStopsTheRun:
    """R4.13 — named, before anything runs."""

    def test_the_error_names_the_step_the_kind_and_the_source(
        self, asks_for_page_images: Path, monkeypatch
    ):
        """Example 1: the one where the source was never told to make it.

        All three, because each answers a different question a reader has:
        which line of the pipeline, which kind, and which source to go and fix.
        """
        _sources(asks_for_page_images, convert=None)
        assert _cli(asks_for_page_images, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(asks_for_page_images, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        assert "describe" in result.output
        assert "page_images" in result.output
        assert "incidents-manual" in result.output
        assert "convert" in result.output, "the message must say what grants the kind"

    def test_the_plan_refuses_what_the_run_refuses(
        self, asks_for_page_images: Path, monkeypatch
    ):
        """Example 1 through `--plan`: the one where the plan knew nothing either.

        R4.13 is knowable from the two configuration files alone, and `--plan`
        reads nothing else. It printed `1 of 1 step(s) would run` and exited 0
        for a pipeline the run then refused: a plan promising work that will not
        happen (R4.12). Found by playground exercise 04.
        """
        _sources(asks_for_page_images, convert=None)
        assert _cli(asks_for_page_images, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(asks_for_page_images, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 2, result.output
        assert "describe" in result.output
        assert "page_images" in result.output
        assert "incidents-manual" in result.output
        assert "would run" not in result.output

    def test_nothing_ran_and_no_run_directory_was_created(
        self, asks_for_page_images: Path, monkeypatch
    ):
        """Example 2: the one where a resolution failure is total (R4.1).

        Zero model calls is the assertion that matters -- the rule's whole
        purpose is to fail before the expensive part, and an error printed after
        one call would satisfy every other assertion here.
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.main as cli

        model = FakeModelClient(responses=[])
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)

        _sources(asks_for_page_images, convert=None)
        _cli(asks_for_page_images, monkeypatch, "sync", PIPELINE)
        _cli(asks_for_page_images, monkeypatch, "run", PIPELINE)

        assert model.call_count == 0
        assert not (asks_for_page_images / "runs").exists()

    def test_a_source_that_declares_the_kind_resolves(
        self, asks_for_page_images: Path, monkeypatch
    ):
        """Example 3: the one where `convert:` grants it.

        Asserted on the *absence* of this rule's error rather than on a clean
        exit: nothing claims `(text/markdown, page_images)`, so the run still
        stops -- at R8.5, which is the other failure and the other fix. The two
        being distinguishable here is the point of the row.
        """
        _sources(asks_for_page_images, convert="markdown, page_images")
        assert _cli(asks_for_page_images, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(asks_for_page_images, monkeypatch, "run", PIPELINE)

        assert "was never told to make" not in result.output
        assert "nothing converts" in result.output, "R8.5's failure, not R4.13's"

    def test_a_bare_documents_input_is_refused_on_the_kind_nobody_wrote(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example (row 5): the one where the kind is implied.

        `input: documents` is `documents@markdown` (R3.11), so a source
        declaring `convert: [page_images]` cannot answer it either. The rule
        holds on a pipeline whose author never typed a kind at all.
        """
        write_pipeline(workspace, steps=["extract"])
        _sources(workspace, convert="page_images")
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        assert "markdown" in result.output
        assert "incidents-manual" in result.output
