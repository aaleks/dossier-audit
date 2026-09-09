"""R8.6, at the CLI — `dossier run` says which documents failed to convert.

The rule's sentence has two halves and they sit at different tiers. That
`convert_source` isolates a failure to its own document is a unit claim, proved
in `tests/unit/test_R008_6__a_conversion_failure_is_isolated.py`. That *the run
says which document failed and why* is something a person observes, and it was
not true: found by `/quality`, `_execute` read `converted.text` and never
`converted.failed`, so a document that failed conversion was not pinned, not
reported, and the command exited 0.

The shape of that bug is the one this project cares most about. `dossier convert`
exited 1 on the identical failure; `dossier run` exited 0 and produced an audit
covering less than it claimed to — which is the failure `application/run.py`'s
own module docstring names as the reason its two failure modes are kept apart.
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
    return json.dumps({"document": document, "fields": []})


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """A workspace holding three documents, none converted yet."""
    write_pipeline(workspace, steps=["extract"])
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return workspace


def _break_one_document(workspace: Path, monkeypatch, key: str) -> None:
    """Make the markdown converter refuse exactly one document's bytes.

    A truncated PDF is what the rule's example describes; with only a markdown
    converter shipped, refusing one payload is the same shape and needs no new
    dependency.
    """
    from dossier.infrastructure.converters.markdown_text import MarkdownTextConverter

    target = (workspace / "inbox" / "incidents" / key).read_bytes()
    original = MarkdownTextConverter.convert

    def selective(self, payload: bytes, options):
        if payload == target:
            raise ValueError("unexpected end of file")
        return original(self, payload, options)

    monkeypatch.setattr(MarkdownTextConverter, "convert", selective)


class TestARunSaysWhatItCouldNotRead:
    """R8.6 — a partial audit is useful; a silent one is not."""

    def test_the_failed_document_is_named_and_the_run_exits_non_zero(
        self, synced: Path, monkeypatch
    ):
        """Example 1 at the CLI: the one where a document cannot be read.

        Exit code and name, both. A run that reported the failure and exited 0
        would still be quotable as a clean audit by anything reading `$?`.
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.main as cli

        _break_one_document(synced, monkeypatch, "INC-4822.md")
        monkeypatch.setattr(
            cli,
            "build_model_client",
            lambda model_id: FakeModelClient(
                responses=[_answer("INC-4821.md"), _answer("audit-note.md")]
            ),
            raising=False,
        )

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        assert "INC-4822.md" in result.output
        assert "unexpected end of file" in result.output

    def test_the_other_documents_are_still_audited(self, synced: Path, monkeypatch):
        """Example 2 at the CLI: the one where two of three still run.

        The point of isolating a failure is that the rest of the work survives
        it. A run that refused everything because one document was unreadable
        would be the opposite mistake and just as wrong.
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.main as cli

        _break_one_document(synced, monkeypatch, "INC-4822.md")
        model = FakeModelClient(
            responses=[_answer("INC-4821.md"), _answer("audit-note.md")]
        )
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)

        _cli(synced, monkeypatch, "run", PIPELINE)

        assert model.call_count == 2, "the two readable documents were audited"

    def test_the_manifest_pins_only_what_was_actually_read(
        self, synced: Path, monkeypatch
    ):
        """The one where the run's own record agrees with what it reported.

        A manifest pinning a document the run never converted would claim
        coverage that did not happen -- and a replay of it would fail for a
        reason nobody could trace back to this afternoon.
        """
        from tests.fakes import FakeModelClient

        import dossier.cli.main as cli

        _break_one_document(synced, monkeypatch, "INC-4822.md")
        monkeypatch.setattr(
            cli,
            "build_model_client",
            lambda model_id: FakeModelClient(
                responses=[_answer("INC-4821.md"), _answer("audit-note.md")]
            ),
            raising=False,
        )

        _cli(synced, monkeypatch, "run", PIPELINE)

        manifest = json.loads(
            next((synced / "runs").rglob("manifest.json")).read_text(encoding="utf-8")
        )
        pinned = {document["key"] for document in manifest["plan"]["documents"]}
        assert "INC-4822.md" not in pinned
        assert pinned == {"INC-4821.md", "audit-note.md"}

    def test_a_run_where_every_document_fails_does_not_report_success(
        self, synced: Path, monkeypatch
    ):
        """Counter-example (row 4) at the CLI: the worst case, and the loudest.

        Every document unreadable. Before this was fixed the run pinned zero
        documents, ran zero stages, printed no failure and exited 0 -- an audit
        that covered nothing and said so nowhere.
        """
        from tests.fakes import NoModelClient

        import dossier.cli.main as cli
        from dossier.infrastructure.converters.markdown_text import MarkdownTextConverter

        def always_fails(self, payload: bytes, options):
            raise ValueError("cannot read")

        monkeypatch.setattr(MarkdownTextConverter, "convert", always_fails)
        monkeypatch.setattr(
            cli, "build_model_client", lambda model_id: NoModelClient(), raising=False
        )

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        assert "cannot read" in result.output
        for key in ("INC-4821.md", "INC-4822.md", "audit-note.md"):
            assert key in result.output, "ten reasons are ten pieces of evidence"
