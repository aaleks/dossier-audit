"""R5.12 — `dossier run` says how many tokens each step spent, and a document
served from cache spent none.

Observed from the CLI, because the line a person reads is the claim: it is where
the cache's whole value becomes a number. No component makes it true alone --
the provider reports what an answer cost (R9.18), the stage sums its attempts
(R5.11), the run adds up what it asked and ignores what it read, and
`step_line` writes the figure the terminal and the MLflow description share.

The provider is registered the way an installed package would register it
(R9.1). Its client answers every document by abstaining -- valid output for any
document (R6.5) -- and says each answer cost 1204 tokens in and 212 out, the
figures `_fixtures.md` gives. Nothing opens a socket.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import register_provider
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
MODEL = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")
FRESH = "extract: 3 document(s) · 0 from cache · 0 failed · 3,612 tokens in · 636 out"
CACHED = "extract: 3 document(s) · 3 from cache · 0 failed"


class Provider:
    """A provider package's factory, whose clients say what each answer cost.

    `reporting=False` is a provider that says nothing -- an OpenWebUI that
    strips `usage` (R9.18 row 4). `refusing` names documents answered with
    something that is not JSON, every time, so they fail after R6.2's retry.
    """

    def __init__(self, *, reporting: bool = True, refusing: frozenset[str] = frozenset()):
        self.reporting = reporting
        self.refusing = refusing
        self.calls = 0

    def __call__(self, model_id: str, *, url: str, api_key: str | None = None):
        return _Client(model_id, self)


class _Client:
    def __init__(self, model_id: str, provider: Provider) -> None:
        self.model_id = model_id
        self._provider = provider

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        from dossier.domain.ports import Reply

        self._provider.calls += 1
        # The document this call is about, as the stage wrapped it (R3.13).
        document = re.search(r'<document key="([^"]+)">', prompt).group(1)
        if document in self._provider.refusing:
            text = "no JSON here"
        else:
            text = json.dumps(
                {
                    "document": document,
                    "fields": [
                        {"field": field, "value": None, "reason": "not stated in document"}
                        for field in FIELDS
                    ],
                }
            )
        if not self._provider.reporting:
            return text
        return Reply(text, input_tokens=1204, output_tokens=212)


def _serve(monkeypatch, provider: Provider) -> Provider:
    register_provider(monkeypatch, "ollama", provider, default_url="http://localhost:11434")
    return provider


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _synced(workspace: Path, monkeypatch) -> None:
    write_pipeline(workspace, model=MODEL)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output


def _step_line(output: str) -> str:
    (line,) = [
        line.strip() for line in output.splitlines() if line.strip().startswith("extract:")
    ]
    return line


class TestARunSaysWhatEachStepSpent:
    """R5.12 — `dossier run` says how many tokens each step spent, and a document
    served from cache spent none."""

    def test_a_fresh_run_says_what_it_spent(self, workspace: Path, monkeypatch):
        """Row 1: the one where three documents are asked, at 1204/212 each."""
        _serve(monkeypatch, Provider())
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _step_line(result.output) == FRESH

    def test_a_run_served_from_cache_spent_nothing(self, workspace: Path, monkeypatch):
        """Row 2: the one where the same run again is served entirely from cache."""
        provider = _serve(monkeypatch, Provider())
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _step_line(result.output) == CACHED
        assert provider.calls == 3

    def test_only_the_document_that_changed_is_paid_for(self, workspace: Path, monkeypatch):
        """Row 3: the one where only `INC-4822` changed since."""
        _serve(monkeypatch, Provider())
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        changed = workspace / "inbox" / "incidents" / "INC-4822.md"
        changed.write_text(
            changed.read_text(encoding="utf-8") + "\nUpdated.\n", encoding="utf-8"
        )
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert _step_line(result.output).endswith(
            "· 2 from cache · 0 failed · 1,204 tokens in · 212 out"
        )

    def test_a_document_that_failed_was_still_paid_for(self, workspace: Path, monkeypatch):
        """Row 4: the one where `INC-4822` fails validation twice, 1204/212 each time.

        Two documents answered once and one refused twice: 4,816 in and 848 out,
        though nothing was written for the one that failed.
        """
        _serve(monkeypatch, Provider(refusing=frozenset({"INC-4822.md"})))
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert _step_line(result.output) == (
            "extract: 3 document(s) · 0 from cache · 1 failed · 4,816 tokens in · 848 out"
        )

    def test_a_provider_that_says_nothing_is_not_a_free_run(self, workspace: Path, monkeypatch):
        """Row 5, a counter-example: the one where the provider reports no counts."""
        _serve(monkeypatch, Provider(reporting=False))
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert _step_line(result.output) == (
            "extract: 3 document(s) · 0 from cache · 0 failed · tokens not reported"
        )

    def test_planning_spends_nothing_and_says_nothing(self, workspace: Path, monkeypatch):
        """Row 6, a counter-example: the one that is `dossier run --plan`."""
        provider = _serve(monkeypatch, Provider())
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert "tokens" not in result.output
        assert provider.calls == 0
