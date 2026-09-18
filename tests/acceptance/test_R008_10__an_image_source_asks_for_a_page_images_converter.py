"""R8.10 — the default kind is read from a declared table.

The rule itself is a domain decision and is proved row by row in
`tests/unit/test_R008_10__the_default_kind_is_read_from_a_declared_table.py`.
What is proved here is the one row a person actually observes: row 4, where the
default decides *which* pair R8.5 reports as unclaimed.

That distinction is the whole point of the rule. Before it, a folder of
screenshots resolved to `(image/png, markdown)`, so `dossier convert` sent the
reader off to install a converter that would turn an image into text -- which is
the one thing an image with no text layer cannot honestly supply. The run
stopping is correct either way; the pair it names is what tells the reader what
to install.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

PIPELINE = "image-audit"

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "documents"
    / "images"
    / "INC-5720-checkout-latency-postmortem.png"
)


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


@pytest.fixture
def image_workspace(workspace: Path) -> Path:
    """A workspace holding `INC-5720` and nothing else, from a silent source.

    A source of its own rather than a PNG dropped into `inbox/incidents/`: the
    counts the other acceptance tests assert are claims about that folder, and a
    fourth document in it would change every one of them.

    The source declares no `convert:`, which is what puts the default table in
    play at all (R8.3 row 3).
    """
    images = workspace / "inbox" / "images"
    images.mkdir(parents=True)
    shutil.copy(FIXTURE, images / FIXTURE.name)

    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: incidents-screenshots\n    type: folder\n    path: inbox/images/\n",
        encoding="utf-8",
    )

    pipeline = workspace / "pipelines" / PIPELINE
    shutil.copytree(workspace / "pipelines" / "incident-audit", pipeline)
    (pipeline / "pipeline.yaml").write_text(
        "sources: [incidents-screenshots]\n"
        "\n"
        "model: anthropic:claude-sonnet-4-5-20250929\n"
        "\n"
        "steps:\n"
        "  - id: extract\n"
        "    prompt: prompts/01_extract.md\n"
        "    input: documents\n"
        "    mode: per_file\n"
        "    output: schemas/incident.yaml\n",
        encoding="utf-8",
    )
    return workspace


class TestAnImageSourceAsksForTheConverterItCanUse:
    """R8.10 row 4 — the default decides which pair must be claimed."""

    def test_an_unconverted_screenshot_names_the_page_images_pair(
        self, image_workspace: Path, monkeypatch
    ):
        """The one where an image asks for an image converter.

        `page_images`, not `markdown`. The run stops either way -- nothing
        claims the pair -- and the pair it prints is the actionable half of the
        message (R8.5 row 1).
        """
        synced = _run(image_workspace, monkeypatch, "sync", PIPELINE)
        assert synced.exit_code == 0, synced.output

        result = _run(image_workspace, monkeypatch, "convert", PIPELINE)

        assert result.exit_code != 0, result.output
        assert "image/png" in result.output
        assert "page_images" in result.output
        assert "markdown'" not in result.output, (
            "the unclaimed pair is (image/png, page_images); naming markdown "
            "here would send the reader to install a converter that turns an "
            "image with no text layer into text"
        )

    def test_the_screenshot_is_held_before_any_of_this(
        self, image_workspace: Path, monkeypatch
    ):
        """The one where the failure is conversion, not sync.

        A PNG is a document like any other: it syncs, it is hashed, it gets a
        ledger row. Only the pair it resolves to is unclaimed, which is R8.5's
        shape rather than a source that could not be read (R1.9).
        """
        result = _run(image_workspace, monkeypatch, "sync", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "1 new" in result.output
