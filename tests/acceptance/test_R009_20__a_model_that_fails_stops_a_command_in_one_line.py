"""R9.20 — a model that cannot be reached, or refuses, stops any command asking
it in one line naming the pipeline, never a traceback.

`dossier run` always said it in one line. `calibrate` and `eval` ask the judge,
and let the same failure out as a Python traceback: a live calibration against a
stub that was not running printed one (R11.23). The failure is the same, and so
is what a person does about it, so the line is the same too.

The client that fails is a fake raising what the real ones raise. What the
message holds -- the URL, the status, the attempts, and never the key -- is the
client's, and is proved where the client is (R9.8 row 1, R9.12 row 4, R9.17
row 3). This proves what the command does with it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import GOLD, _cli
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, PIPELINE, SOURCE_ID, SOURCE_TYPE, IssueTracker

from dossier.infrastructure.models._http import ModelRequestFailed

URL = "http://localhost:8080/api/chat/completions"
UNREACHABLE = f"{URL} failed: [Errno 111] Connection refused (after 3 attempts)"
REFUSED = f"{URL} answered 401 Unauthorized"
# `_fixtures.md` writes the revision as `1c0f8e6b`; a real one is a 40-character
# commit (R9.5).
HF = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5


class FailingModel:
    """A model whose every request ends as the real client's would, having failed."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.calls += 1
        raise self.error


class Judge:
    """A judge that answers every claim it is shown as supported."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        assert "<claim>" in prompt, "eval reproduces the run and asks only the judge"
        return json.dumps({"supported": True, "evidence": "the paragraph that says so"})


def _serve(monkeypatch, model) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)


def _said_in_one_line(result, error: str) -> None:
    """Exit 2, the line on standard error, and no exception but the exit itself."""
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert f"{PIPELINE}: POST {error}" in result.stderr.splitlines(), result.stderr


def _cases() -> list[dict]:
    keys = sorted(ISSUES)
    return [
        {
            "document": keys[index % len(keys)],
            "answer": f"candidate answer {index}",
            "supported": index < 12,
            "verified_by": "a.aleks",
            "verified_at": "2026-09-15",
        }
        for index in range(20)
    ]


def _calibratable(workspace: Path, monkeypatch, *, model: str = FailingModel.model_id) -> Path:
    """A synced workspace whose gold set carries a twenty-case sample."""
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, sources=[SOURCE_ID], model=model)
    path.write_text(path.read_text(encoding="utf-8") + f"gold: {GOLD}/\n", encoding="utf-8")
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    samples = workspace / "gold" / "incidents" / "samples"
    samples.mkdir(parents=True)
    (samples / "root_cause.jsonl").write_text(
        "\n".join(json.dumps(case) for case in _cases()) + "\n", encoding="utf-8"
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


class TestAModelThatFailsStopsACommandInOneLine:
    """R9.20 — the line `run` prints, printed by every command that asks a model."""

    def test_calibrate_with_nothing_listening_says_so_in_one_line(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one the live calibration found.

        Refused on the first case, after R9.17's retries. Nothing was measured,
        so nothing is written beside the gold set either.
        """
        _calibratable(workspace, monkeypatch)
        _serve(monkeypatch, FailingModel(ModelRequestFailed(f"POST {UNREACHABLE}")))

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        _said_in_one_line(result, UNREACHABLE)
        assert not (workspace / "gold" / "incidents" / "calibrations").exists()

    def test_eval_whose_judge_refuses_its_key_says_so_in_one_line(
        self, judged_run: tuple[Path, str], monkeypatch
    ):
        """Row 2: the one where the verdict is not cached and the judge answers 401."""
        workspace, _ = judged_run
        _serve(monkeypatch, FailingModel(ModelRequestFailed(f"POST {REFUSED}")))

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        _said_in_one_line(result, REFUSED)

    def test_a_comparison_whose_judge_is_unreachable_says_so_in_one_line(
        self, judged_run: tuple[Path, str], monkeypatch
    ):
        """Row 3: the one where the change gate is the command that asks the judge.

        The second run is the first served from cache, under a run id of its
        own, so the two are comparable (R7.8) and both reach the judge.
        """
        workspace, first = judged_run
        again = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert again.exit_code == 0, again.output
        second = re.search(r"^run (\S+)", again.output, re.MULTILINE).group(1)
        _serve(monkeypatch, FailingModel(ModelRequestFailed(f"POST {UNREACHABLE}")))

        result = _cli(
            workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD, "--compare", first, second
        )

        _said_in_one_line(result, UNREACHABLE)

    def test_calibrate_with_no_endpoint_names_the_variable(self, workspace: Path, monkeypatch):
        """Row 4: the one where nothing says where the judge is served (R9.2 row 3).

        The real `build_model_client`, so the error is the one config raises.
        """
        monkeypatch.delenv("DOSSIER_HF_URL", raising=False)
        _calibratable(workspace, monkeypatch, model=HF)

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 2, result.output
        assert isinstance(result.exception, SystemExit), result.exception
        (line,) = result.stderr.splitlines()
        assert line.startswith(f"{PIPELINE}: DOSSIER_HF_URL is not set"), line

    def test_run_with_nothing_listening_says_so_in_one_line(self, workspace: Path, monkeypatch):
        """Row 5: the one that was already true, and is now stated."""
        (workspace / "sources.yaml").write_text(
            f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
        )
        write_pipeline(workspace, sources=[SOURCE_ID])
        register_connector(
            monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
        )
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        _serve(monkeypatch, FailingModel(ModelRequestFailed(f"POST {UNREACHABLE}")))

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        _said_in_one_line(result, UNREACHABLE)

    def test_an_eval_whose_verdicts_are_cached_asks_nothing_and_completes(
        self, judged_run: tuple[Path, str], monkeypatch
    ):
        """Row 6, a counter-example: the one with nothing to fail.

        The first eval caches the verdict (R7.18). The second is served it, so
        a judge nobody can reach is never built, let alone asked.
        """
        workspace, _ = judged_run
        _serve(monkeypatch, Judge())
        first = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
        assert first.exit_code == 0, first.output
        unreachable = FailingModel(ModelRequestFailed(f"POST {UNREACHABLE}"))
        _serve(monkeypatch, unreachable)

        result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert unreachable.calls == 0

    def test_an_error_that_is_not_a_models_keeps_its_traceback(
        self, workspace: Path, monkeypatch
    ):
        """Row 7, a counter-example: the one nobody expected.

        A bug is not a line. Turned into one, it would read as something the
        reader can fix, and they cannot.
        """
        _calibratable(workspace, monkeypatch)
        bug = RuntimeError("a bug, not a model")
        _serve(monkeypatch, FailingModel(bug))

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exception is bug
        assert result.exit_code == 1
        assert f"{PIPELINE}: a bug" not in result.stderr
