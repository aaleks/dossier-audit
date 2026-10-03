"""R21.7 — a masked pipeline that cannot be masked is refused before any model call.

Fail closed: with `masking:` declared, what cannot be masked is never sent
unmasked instead. Each row is a configuration that would leave a value
unmasked -- a picture, no masker, no threshold, a type nothing finds -- and
each stops with exit 2 before the model is asked anything. The model is
`NoModelClient`, which fails at the call site if it is reached at all.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakeMasker, NoModelClient
from tests.pipelines import write_pipeline

PIPELINE = "incident-audit"
SOURCES = "sources:\n  - id: incidents\n    type: folder\n    path: inbox/tickets/\n"
DECLARATION = (
    "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON, IBAN_CODE]\n"
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _workspace(
    workspace: Path,
    monkeypatch,
    *,
    declaration: str | None = DECLARATION,
    inputs: dict[str, str] | None = None,
    masker: FakeMasker | None = None,
) -> Path:
    """`INC-4821` in a folder, a pipeline declaring `declaration`, and no model to reach."""
    import dossier.cli.bootstrap as cli

    ticket = workspace / "inbox" / "tickets" / "INC-4821.md"
    ticket.parent.mkdir(parents=True, exist_ok=True)
    ticket.write_text("# INC-4821\n\nErika Mustermann called.\n", encoding="utf-8")
    (workspace / "sources.yaml").write_text(SOURCES, encoding="utf-8")
    path = write_pipeline(workspace, name=PIPELINE, sources=["incidents"], inputs=inputs)
    if declaration is not None:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(declaration, encoding="utf-8")
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    if masker is not None:
        monkeypatch.setattr(cli, "build_masker", lambda name: masker, raising=False)
    return path


class TestAnUnmaskablePipelineIsRefusedBeforeAnyCall:
    """R21.7 — what cannot be masked stops the command; it is never sent instead."""

    def test_a_step_reading_page_images_is_refused_at_load(self, workspace: Path, monkeypatch):
        """Row 1: the one where a step reads page images.

        The client's name is in the pixels, and nothing here masks pixels.
        """
        _workspace(
            workspace,
            monkeypatch,
            inputs={"extract": "documents@page_images"},
            masker=FakeMasker(),
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "'extract'" in result.output
        assert "page_images" in result.output
        assert "masking" in result.output

    def test_a_masker_no_package_provides_is_refused(self, workspace: Path, monkeypatch):
        """Row 2: the one where no masker is installed.

        Refused naming the extra that installs it. The installed entry points
        are emptied as an installation without the extra has none.
        """
        import dossier.infrastructure.maskers.registry as registry

        _workspace(workspace, monkeypatch)
        monkeypatch.setattr(registry, "entry_points", lambda group: [])
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "'presidio'" in result.output
        assert "--extra masking" in result.output

    def test_a_declaration_with_no_threshold_is_refused_naming_the_file_and_key(
        self, workspace: Path, monkeypatch
    ):
        """Row 3: the one where the author left the threshold out.

        `dossier` ships no number to fall back on: which recognisers count is
        the author's decision, and an absent one is a mistake, not a default.
        """
        _workspace(
            workspace,
            monkeypatch,
            declaration=DECLARATION.replace("score_threshold: 0.5\n", ""),
            masker=FakeMasker(),
        )

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "cid.yaml" in result.output
        assert "score_threshold" in result.output

    def test_a_type_nothing_recognises_is_refused_naming_it(self, workspace: Path, monkeypatch):
        """Row 4: the one where the declaration asks for a type nothing finds.

        A type no recogniser and no pattern provides would be silently left
        unmasked: the author believes `CLIENT_ID` is masked, and nothing is.
        """
        _workspace(
            workspace,
            monkeypatch,
            declaration=DECLARATION.replace("[PERSON, IBAN_CODE]", "[PERSON, CLIENT_ID]"),
            masker=FakeMasker(),
        )
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "CLIENT_ID" in result.output

    def test_the_same_page_images_step_without_masking_loads(
        self, workspace: Path, monkeypatch
    ):
        """Row 5, a counter-example: the one where nothing is declared.

        The step that reads pictures is refused only because masking was
        asked for: without it, the pipeline loads as it always did.
        """
        from dossier.config.load import load_pipeline
        from dossier.infrastructure.models.registry import available_providers

        path = _workspace(
            workspace,
            monkeypatch,
            declaration=None,
            inputs={"extract": "documents@page_images"},
        )

        config = load_pipeline(path, providers=available_providers())

        assert config.steps[0].inputs == ["documents@page_images"]
