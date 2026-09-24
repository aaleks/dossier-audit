"""R9.19 — `dossier run` asks a model about at most `N` of a step's documents at
once, and nothing it writes depends on `N`.

Observed from the CLI, because `--concurrency` and `DOSSIER_CONCURRENCY` are
what a person sets, and the step line and `runs/` are what they read. No
component makes the rule true alone: the value is read and refused before any
work, the run hands a step's documents to that many workers, and the results
are put back in document order before anything is printed or compared.

The provider is registered the way an installed package would register it
(R9.1). Its client holds every answer at a gate, so what it counts is how many
calls were in flight together rather than how quickly they happened to arrive:
a run asking one at a time never opens a gate set for three, and is answered
anyway after `PATIENCE`, so a red run fails on what was counted instead of
hanging. Nothing opens a socket.

The fixture inbox holds `INC-4821.md`, `INC-4822.md` and `audit-note.md`, in
that document order; they stand for the three incidents the spec's rows name.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path

import pytest
from tests.fakes import register_provider
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
MODEL = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")
DOCUMENTS = ("INC-4821.md", "INC-4822.md", "audit-note.md")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# How long a call waits for company before it is answered alone. Long enough
# that a run asking at once always meets; short enough that a run asking one at
# a time fails in seconds.
PATIENCE = 2.0
# How long an answer is held once the gate is open, so calls that overlap are
# seen to: without it a run that should ask one at a time could ask three and
# never have two in flight together.
HOLD = 0.05


class Provider:
    """A provider package's factory, whose clients answer at a gate.

    The gate opens once `meet` calls are in flight together, or every document
    not yet answered is, so the last of an uneven batch is not kept waiting for
    company that is not coming. `order` names the order answers are given in
    once it is open. `refusing` is an endpoint that refuses every request,
    after the gate, so which calls were started is decided before any fails.
    """

    def __init__(
        self, *, meet: int = 1, order: tuple[str, ...] = (), refusing: bool = False
    ) -> None:
        self.meet = meet
        self.order = order
        self.refusing = refusing
        self.asked: list[str] = []
        self.most_at_once = 0
        self._in_flight = 0
        self._answered: list[str] = []
        self._open = False
        self._gate = threading.Condition()

    def __call__(self, model_id: str, *, url: str, api_key: str | None = None):
        return _Client(model_id, self)

    def answer(self, document: str) -> None:
        with self._gate:
            self.asked.append(document)
            self._in_flight += 1
            self.most_at_once = max(self.most_at_once, self._in_flight)
            waiting = len(DOCUMENTS) - len(self._answered)
            if self._in_flight >= min(self.meet, waiting):
                self._open = True
            self._gate.notify_all()
            self._gate.wait_for(lambda: self._open and self._turn(document), timeout=PATIENCE)
        time.sleep(HOLD)
        with self._gate:
            self._in_flight -= 1
            self._answered.append(document)
            self._gate.notify_all()

    def _turn(self, document: str) -> bool:
        if not self.order:
            return True
        return self.order[len(self._answered)] == document


class _Client:
    def __init__(self, model_id: str, provider: Provider) -> None:
        self.model_id = model_id
        self._provider = provider

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        from dossier.domain.ports import Reply
        from dossier.infrastructure.models._http import ModelRequestFailed

        # The document this call is about, as the stage wrapped it (R3.13).
        document = re.search(r'<document key="([^"]+)">', prompt).group(1)
        self._provider.answer(document)
        if self._provider.refusing:
            raise ModelRequestFailed(f"POST http://localhost:11434/api/chat refused {document}")
        text = json.dumps(
            {
                "document": document,
                "fields": [
                    {"field": field, "value": None, "reason": "not stated in document"}
                    for field in FIELDS
                ],
            }
        )
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


def _extract_dir(workspace: Path) -> Path:
    (run,) = [path for path in (workspace / "runs").iterdir() if path.is_dir()]
    return run / "extract"


def _written(workspace: Path) -> dict[str, object]:
    """What the run wrote for `extract`: artifacts as bytes, records without `run_id`."""
    written: dict[str, object] = {}
    for path in sorted(_extract_dir(workspace).iterdir()):
        content = path.read_bytes()
        record = json.loads(content)
        if isinstance(record, dict) and "run_id" in record:
            written[path.name] = {k: v for k, v in record.items() if k != "run_id"}
        else:
            written[path.name] = content
    return written


class TestARunAsksAboutSeveralDocumentsAtOnce:
    """R9.19 — `dossier run` asks a model about at most `N` of a step's documents
    at once, and nothing it writes depends on `N`."""

    def test_three_at_once_says_what_one_at_a_time_says(self, workspace: Path, monkeypatch):
        """Row 1: the one where all three are asked before any is answered."""
        provider = _serve(monkeypatch, Provider(meet=3))
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--concurrency", "3")

        assert result.exit_code == 0, result.output
        assert provider.most_at_once == 3
        assert _step_line(result.output) == (
            "extract: 3 document(s) · 0 from cache · 0 failed · 3,612 tokens in · 636 out"
        )

    def test_the_order_answers_came_in_changes_nothing_written(
        self, workspace: Path, tmp_path: Path, monkeypatch
    ):
        """Row 2: the one answered last-first, against the same run with no flag."""
        _serve(monkeypatch, Provider(meet=3, order=tuple(reversed(DOCUMENTS))))
        _synced(workspace, monkeypatch)
        assert (
            _cli(workspace, monkeypatch, "run", PIPELINE, "--concurrency", "3").exit_code == 0
        )

        alone = tmp_path / "alone"
        shutil.copytree(FIXTURES, alone)
        _serve(monkeypatch, Provider())
        _synced(alone, monkeypatch)
        assert _cli(alone, monkeypatch, "run", PIPELINE).exit_code == 0

        assert _written(workspace) == _written(alone)
        assert len(_written(workspace)) == 6

    def test_the_machine_says_how_many(self, workspace: Path, monkeypatch):
        """Row 3: the one with `DOSSIER_CONCURRENCY=2` in `.env` and no flag."""
        provider = _serve(monkeypatch, Provider(meet=2))
        _synced(workspace, monkeypatch)
        (workspace / ".env").write_text("DOSSIER_CONCURRENCY=2\n", encoding="utf-8")

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert provider.most_at_once == 2

    def test_the_command_line_wins_over_the_machine(self, workspace: Path, monkeypatch):
        """Row 4: the one with `DOSSIER_CONCURRENCY=2` and `--concurrency 3`."""
        provider = _serve(monkeypatch, Provider(meet=3))
        _synced(workspace, monkeypatch)
        (workspace / ".env").write_text("DOSSIER_CONCURRENCY=2\n", encoding="utf-8")

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--concurrency", "3")

        assert result.exit_code == 0, result.output
        assert provider.most_at_once == 3

    def test_unset_is_one_at_a_time(self, workspace: Path, monkeypatch):
        """Row 5: the one with neither set: the run this rule found."""
        provider = _serve(monkeypatch, Provider(meet=1))
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert provider.most_at_once == 1
        assert provider.asked == list(DOCUMENTS)

    def test_a_refused_request_starts_nothing_more(self, workspace: Path, monkeypatch):
        """Row 6: the one where every request is refused, at `--concurrency 2`."""
        provider = _serve(monkeypatch, Provider(meet=2, refusing=True))
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--concurrency", "2")

        assert result.exit_code == 2
        assert sorted(provider.asked) == ["INC-4821.md", "INC-4822.md"]
        # The first failing document's error, in document order: the one a run
        # asking one at a time stops with.
        assert "refused INC-4821.md" in result.output
        assert "refused INC-4822.md" not in result.output

    @pytest.mark.parametrize(
        ("flag", "setting", "said"),
        [
            ("0", None, "--concurrency is '0'"),
            ("-1", None, "--concurrency is '-1'"),
            ("four", None, "--concurrency is 'four'"),
            (None, "2.5", "DOSSIER_CONCURRENCY is '2.5'"),
        ],
    )
    def test_a_value_that_is_not_a_count_is_refused_before_any_work(
        self, workspace: Path, monkeypatch, flag, setting, said
    ):
        """Row 7, a counter-example: `0`, `-1`, `four`, and `2.5` in `.env`."""
        provider = _serve(monkeypatch, Provider())
        _synced(workspace, monkeypatch)
        if setting is not None:
            (workspace / ".env").write_text(
                f"DOSSIER_CONCURRENCY={setting}\n", encoding="utf-8"
            )
        args = ["run", PIPELINE] + (["--concurrency", flag] if flag is not None else [])

        result = _cli(workspace, monkeypatch, *args)

        assert result.exit_code == 2
        assert f"{said}; it takes a whole number of at least 1." in result.output
        assert provider.asked == []
        assert not (workspace / "runs").exists() or not any((workspace / "runs").iterdir())

    def test_a_pipeline_does_not_say_how_fast_it_is_run(self, workspace: Path, monkeypatch):
        """Row 8, a counter-example: `concurrency: 3` in `pipeline.yaml`."""
        provider = _serve(monkeypatch, Provider())
        _synced(workspace, monkeypatch)
        path = workspace / "pipelines" / PIPELINE / "pipeline.yaml"
        path.write_text(path.read_text(encoding="utf-8") + "concurrency: 3\n", encoding="utf-8")

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2
        assert "concurrency" in result.output
        assert provider.asked == []
