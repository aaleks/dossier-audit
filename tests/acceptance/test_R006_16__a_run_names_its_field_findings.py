"""R6.16 — `dossier run` names every field finding it produced, with the reason
the check gave.

The finding this test is built from is the one playground exercise 05 hit against
a real model: every field cites its document without the extension the key
carries, so every field is `invalid` under R6.3 and every value is right. A run
reported `0 failed` over all of them, because `field_failures` had no caller.

Acceptance rather than unit, because the claim is about what a person reads at
the end of `dossier run` -- the step line and the lines under it -- and no single
component produces that.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline

from dossier.domain.ports import ItemRef, RawItem

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"

NOTES = {
    "INC-4821": "# INC-4821\n\nSeverity was assessed as major.\n",
    "INC-4822": "# INC-4822\n\nSeverity was assessed as minor.\n",
}


def _answer(document: str, *, cites: str, span: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "severity",
                    "value": "major",
                    "source": {"document": cites, "span": span},
                }
            ],
        }
    )


class Notes:
    """Two documents, keyed as an issue tracker keys them."""

    lists_everything = False
    media_type = "text/markdown"

    def list(self, since: datetime | None = None):
        for key in sorted(NOTES):
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(
            key=key,
            payload=NOTES[key].encode("utf-8"),
            media_type=self.media_type,
            remote_version=None,
        )

    def attachments(self, key: str):
        return iter(())


class Model:
    """Answers each document as the `answers` mapping says, routed by the prompt."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        asked = [key for key in self.answers if f"# {key}\n" in prompt]
        assert len(asked) == 1, f"expected one document in the prompt, found {asked}"
        return self.answers[asked[0]]


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _run(workspace: Path, monkeypatch, answers: dict[str, str]):
    import dossier.cli.main as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID], steps=["extract"])
    register_connector(monkeypatch, SOURCE_TYPE, lambda config, *, workspace: Notes())
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model(answers))

    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    return _cli(workspace, monkeypatch, "run", PIPELINE)


@pytest.fixture
def ungrounded(workspace: Path, monkeypatch):
    """Both documents citing a key with no extension, as exercise 05's run did."""
    return _run(
        workspace,
        monkeypatch,
        {
            key: _answer(key, cites=f"{key}-not-an-input", span="Severity was assessed")
            for key in NOTES
        },
    )


@pytest.fixture
def clean(workspace: Path, monkeypatch):
    """Both documents citing themselves, with a span that locates."""
    return _run(
        workspace,
        monkeypatch,
        {key: _answer(key, cites=key, span="Severity was assessed as") for key in NOTES},
    )


class TestARunNamesItsFieldFindings:
    """R6.16 — the reason is already computed; this is it reaching a person."""

    def test_the_step_line_counts_them(self, ungrounded):
        """Row 1 — counted beside `described`, in the step's own line."""
        line = next(
            line
            for line in ungrounded.output.splitlines()
            if line.strip().startswith("extract:")
        )

        assert "2 finding(s)" in line, line

    def test_each_finding_names_its_document_field_and_reason(self, ungrounded):
        """Row 2 — the detail `check_field` composed, verbatim."""
        output = ungrounded.output

        assert "INC-4821" in output
        assert "severity" in output
        assert "which was not an input to this stage" in output
        assert "(R6.3)" in output

    def test_a_finding_is_not_a_failure(self, ungrounded):
        """Row 3 — every artifact was written; the exit code is R6.9's."""
        assert ungrounded.exit_code == 0, ungrounded.output
        assert "0 failed" in ungrounded.output

    def test_a_clean_run_reads_as_it_did(self, clean):
        """Row 5 — no count and no lines when there is nothing to report."""
        assert clean.exit_code == 0, clean.output
        assert "finding" not in clean.output
        assert "(R6.3)" not in clean.output

    def test_a_cached_run_is_as_diagnosable_as_a_fresh_one(
        self, workspace: Path, monkeypatch, ungrounded
    ):
        """Row 4 — grounding is re-derived on a hit (R5.5), so the findings survive."""
        again = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert again.exit_code == 0, again.output
        assert "from cache" in again.output
        assert "2 finding(s)" in again.output
        assert "which was not an input to this stage" in again.output
