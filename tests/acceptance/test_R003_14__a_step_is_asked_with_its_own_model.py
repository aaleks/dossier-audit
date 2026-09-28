"""R3.14 — a step may name its own `model`, and is asked with it; a step that
names none is asked with the pipeline's.

Observed from the CLI, because every layer has to agree for it to be true: the
loader accepted and checked the step's model, resolution recorded it in the
manifest, the run built a client for it at the step's first miss and keyed the
step's artifacts under it, and `--plan` and `--replay` read it back.

Two providers are registered the way installed packages would register them
(R9.1): `ollama` answers `extract`, which names its own model, and `anthropic`
answers `verify`, which names none. Each counts the clients it built and the
documents it was asked about, so which model answered which step is read off
what each provider saw rather than inferred. Nothing opens a socket.

The fixture inbox holds `INC-4821.md`, `INC-4822.md` and `audit-note.md`; they
stand for the three documents the spec's rows name.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.fakes import FakeModelClient, register_connector, register_provider
from tests.pipelines import write_pipeline
from tests.scoring_example import ISSUES, SOURCE_ID, SOURCE_TYPE, IssueTracker

PIPELINE = "incident-audit"
PIPELINE_MODEL = "anthropic:claude-sonnet-4-5-20250929"
EXTRACT_MODEL = "ollama:qwen2.5:7b@sha256:" + "7f3c29a1" * 8
REVISED_MODEL = "hf:Qwen/Qwen2.5-7B-Instruct@" + "1c0f8e6b" * 5
OTHER_PIPELINE_MODEL = "openai:gpt-4o-2024-08-06"
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")
DOCUMENTS = ("INC-4821.md", "INC-4822.md", "audit-note.md")


class Provider:
    """A provider package's factory, counting the clients it built and the calls made.

    Every client abstains for whichever document it is asked about (R6.5), which
    is valid output for `extract` and for `verify` alike.
    """

    def __init__(self) -> None:
        self.built: list[str] = []
        self.asked: list[str] = []

    def __call__(self, model_id: str, *, url: str, api_key: str | None = None):
        self.built.append(model_id)
        return _Client(model_id, self)


class _Client:
    def __init__(self, model_id: str, provider: Provider) -> None:
        self.model_id = model_id
        self._provider = provider

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        document = re.search(r'<document key="([^"]+)">', prompt).group(1)
        self._provider.asked.append(document)
        return json.dumps(
            {
                "document": document,
                "fields": [
                    {"field": field, "value": None, "reason": "not stated in document"}
                    for field in FIELDS
                ],
            }
        )


def _serve(monkeypatch) -> tuple[Provider, Provider]:
    ollama, anthropic = Provider(), Provider()
    register_provider(monkeypatch, "ollama", ollama, default_url="http://localhost:11434")
    register_provider(
        monkeypatch, "anthropic", anthropic, default_url="https://api.anthropic.com/v1"
    )
    monkeypatch.setenv("DOSSIER_ANTHROPIC_API_KEY", "sk-ant-test")
    return ollama, anthropic


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _pipeline(
    workspace: Path,
    *,
    model: str = PIPELINE_MODEL,
    step_models: dict[str, str] | None = None,
) -> Path:
    """`extract` over the documents, then `verify` over the documents and `extract`."""
    return write_pipeline(
        workspace,
        steps=["extract", "verify"],
        inputs={"verify": "[documents, extract]"},
        model=model,
        step_models={"extract": EXTRACT_MODEL} if step_models is None else step_models,
    )


def _synced(workspace: Path, monkeypatch, **pipeline) -> None:
    _pipeline(workspace, **pipeline)
    result = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert result.exit_code == 0, result.output


def _run_dir(workspace: Path) -> Path:
    (run,) = [path for path in (workspace / "runs").iterdir() if path.is_dir()]
    return run


def _manifest(workspace: Path) -> dict:
    return json.loads((_run_dir(workspace) / "manifest.json").read_text(encoding="utf-8"))


def _plan_step(output: str, step: str) -> list[str]:
    """A step's line in `--plan`, and the indented lines beneath it."""
    lines = output.splitlines()
    (start,) = [i for i, line in enumerate(lines) if line[2:].startswith(f"{step}:")]
    beneath = []
    for line in lines[start + 1 :]:
        if not line.startswith("      "):
            break
        beneath.append(line.strip())
    return [lines[start], *beneath]


class TestAStepIsAskedWithItsOwnModel:
    """R3.14 — a step may name its own `model`, and is asked with it."""

    def test_each_step_is_asked_by_its_own_models_provider(self, workspace: Path, monkeypatch):
        """Row 1: `extract` on Ollama, `verify` on the pipeline's Anthropic model."""
        ollama, anthropic = _serve(monkeypatch)
        _synced(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert (ollama.built, sorted(ollama.asked)) == ([EXTRACT_MODEL], list(DOCUMENTS))
        assert (anthropic.built, sorted(anthropic.asked)) == ([PIPELINE_MODEL], list(DOCUMENTS))
        run = _run_dir(workspace)
        for step, model in (("extract", EXTRACT_MODEL), ("verify", PIPELINE_MODEL)):
            records = sorted((run / step).glob("*.meta.json"))
            assert len(records) == 3
            for record in records:
                assert json.loads(record.read_text(encoding="utf-8"))["model"] == model

    def test_the_manifest_records_a_steps_own_model_and_no_other(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: `extract` carries its model, `verify` none, the plan the pipeline's."""
        _serve(monkeypatch)
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

        plan = _manifest(workspace)["plan"]

        steps = {step["id"]: step for step in plan["steps"]}
        assert steps["extract"]["model"] == EXTRACT_MODEL
        assert "model" not in steps["verify"]
        assert plan["model"] == PIPELINE_MODEL

    def test_a_run_served_from_cache_builds_no_client(self, workspace: Path, monkeypatch):
        """Row 3: the same run again: every step from cache, neither model reached."""
        ollama, anthropic = _serve(monkeypatch)
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        ollama.built.clear()
        anthropic.built.clear()

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert (ollama.built, anthropic.built) == ([], [])

    def test_the_plan_sees_a_steps_own_model_move(self, workspace: Path, monkeypatch):
        """Row 4: `extract`'s model changed, then `--plan`."""
        _serve(monkeypatch)
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        _pipeline(workspace, step_models={"extract": REVISED_MODEL})

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _plan_step(result.output, "extract") == [
            "! extract: model changed",
            f"model: {REVISED_MODEL}",
        ]
        assert _plan_step(result.output, "verify") == ["! verify: upstream changed"]

    def test_the_plan_sees_the_pipelines_model_move_for_the_steps_that_use_it(
        self, workspace: Path, monkeypatch
    ):
        """Row 5: the pipeline's `model:` changed, `extract` still naming its own."""
        _serve(monkeypatch)
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        _pipeline(workspace, model=OTHER_PIPELINE_MODEL)

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _plan_step(result.output, "extract") == [
            "  extract: cached",
            f"model: {EXTRACT_MODEL}",
        ]
        assert _plan_step(result.output, "verify") == ["! verify: model changed"]

    def test_a_replay_rebuilds_each_key_with_its_steps_model(
        self, workspace: Path, monkeypatch
    ):
        """Row 6: `dossier run --replay` of that run: reproduced, nothing asked."""
        ollama, anthropic = _serve(monkeypatch)
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        asked = (list(ollama.asked), list(anthropic.asked))

        result = _cli(workspace, monkeypatch, "run", "--replay", str(_run_dir(workspace)))

        assert result.exit_code == 0, result.output
        assert "6 artifact(s) reproduced · no model calls" in result.output
        assert (ollama.asked, anthropic.asked) == asked

    def test_naming_the_pipelines_own_model_is_naming_none(self, workspace: Path, monkeypatch):
        """Row 7: `verify` naming the pipeline's model: every key the same, so cached."""
        _serve(monkeypatch)
        _synced(workspace, monkeypatch)
        assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0
        _pipeline(workspace, step_models={"extract": EXTRACT_MODEL, "verify": PIPELINE_MODEL})

        result = _cli(workspace, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _plan_step(result.output, "verify") == ["  verify: cached"]
        assert "0 of 2 step(s) would run" in result.output

    def test_a_pipeline_whose_steps_name_no_model_records_none(
        self, workspace: Path, monkeypatch
    ):
        """Row 8, a counter-example: no step names a model."""
        ollama, anthropic = _serve(monkeypatch)
        _synced(workspace, monkeypatch, step_models={})

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert ollama.built == []
        assert all("model" not in step for step in _manifest(workspace)["plan"]["steps"])

    def test_an_unpinned_step_model_is_refused_at_load_time(self, workspace: Path, monkeypatch):
        """Row 9, a counter-example: `extract` naming `anthropic:claude-sonnet-4-5`."""
        ollama, anthropic = _serve(monkeypatch)
        _pipeline(workspace, step_models={"extract": "anthropic:claude-sonnet-4-5"})

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2
        assert "pipeline.yaml" in result.output
        assert "steps.0.model" in result.output
        assert "anthropic:claude-sonnet-4-5" in result.output
        assert (ollama.asked, anthropic.asked) == ([], [])

    def test_a_step_model_no_package_provides_is_refused_at_load_time(
        self, workspace: Path, monkeypatch
    ):
        """Row 10, a counter-example: `extract` naming `mistral:mistral-large-2411`."""
        _serve(monkeypatch)
        _pipeline(workspace, step_models={"extract": "mistral:mistral-large-2411"})

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2
        assert "steps.0.model" in result.output
        assert "mistral" in result.output
        assert "anthropic" in result.output and "ollama" in result.output

    def test_calibrate_judges_with_the_pipelines_model(self, workspace: Path, monkeypatch):
        """Row 11, a counter-example: `dossier calibrate` over a pipeline whose `extract`
        names its own model.

        The judge is the pipeline's `model:`: the only client asked for, and the
        model the calibration is written for (R7.14). The documents come from an
        issue tracker, as R7.14's do, because a gold sample is keyed by document.
        """
        import dossier.cli.bootstrap as cli

        (workspace / "sources.yaml").write_text(
            f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
        )
        path = write_pipeline(
            workspace, sources=[SOURCE_ID], step_models={"extract": EXTRACT_MODEL}
        )
        path.write_text(
            path.read_text(encoding="utf-8") + "gold: gold/incidents/\n", encoding="utf-8"
        )
        register_connector(
            monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
        )
        gold = workspace / "gold" / "incidents"
        (gold / "samples").mkdir(parents=True)
        (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
        keys = sorted(ISSUES)
        cases = [
            {
                "document": keys[index % len(keys)],
                "answer": f"candidate answer {index}",
                "supported": index < 12,
                "verified_by": "a.aleks",
                "verified_at": "2026-09-15",
            }
            for index in range(20)
        ]
        (gold / "samples" / "root_cause.jsonl").write_text(
            "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
        )
        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        judge = FakeModelClient(
            responses=[json.dumps({"supported": case["supported"]}) for case in cases]
        )
        asked_for: list[str] = []

        def build(model_id: str):
            asked_for.append(model_id)
            return judge

        monkeypatch.setattr(cli, "build_model_client", build)

        result = _cli(workspace, monkeypatch, "calibrate", PIPELINE, "--gold", "gold/incidents")

        assert result.exit_code == 0, result.output
        assert asked_for == [PIPELINE_MODEL]
        written = json.loads(
            (gold / "calibrations" / "root_cause.json").read_text(encoding="utf-8")
        )
        assert written["judge_model"] == PIPELINE_MODEL
