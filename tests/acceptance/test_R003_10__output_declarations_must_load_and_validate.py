"""R3.10 — every `output` path resolves to a field declaration that loads and declares valid kinds.

The outer loop for the fields slice. A step's `output` used to name a
hand-written JSON Schema; under R6.10 it names a YAML field declaration, and the
JSON Schema is generated from it. What a user observes is the load: a pipeline
whose declaration is sound gets as far as a plan, and one whose declaration
cannot be scored is refused before anything is paid for.

Observed through `dossier run --plan`, because that is the command a person runs
to find out whether a pipeline is sound before running it. No single component
satisfies this: config loading must follow `output` to the file, the domain must
parse the declaration and know the five kinds (R6.10), and the CLI must carry the
message to where a person reads it -- all before a model client is built.

Each refusal asserts the model was never asked for. "Found at load time" is the
whole point of the rule, and a pipeline refused after a client was built has
already read a credential.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
DECLARATION = "schemas/incident.yaml"

# The declaration spec 006 shows, verbatim: five fields, one of each kind.
INCIDENT_YAML = """\
fields:
  loss_amount:      {kind: amount, currency: CHF}
  resolution_date:  {kind: date}
  severity:         {kind: enum, values: [minor, major, critical]}
  affected_systems: {kind: reference}
  root_cause:       {kind: free_text, judge: rubrics/root_cause.md}
"""

KINDS = ("amount", "date", "enum", "reference", "free_text")


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    """A workspace whose documents are already held, so a plan has something to pin.

    Synced with the fixture pipeline before any test rewrites it, which keeps
    each test about loading a declaration rather than about fetching.
    """
    _run(workspace, monkeypatch, "sync", PIPELINE)
    return workspace


@pytest.fixture
def model_calls(monkeypatch) -> list[str]:
    """Every model client the composition root asked for, and every call made."""
    from tests.fakes import FakeModelClient

    import dossier.cli.main as cli

    record: list = []
    client = FakeModelClient(responses=[], calls=record)

    def build(model_id: str):
        record.append(f"built a client for {model_id}")
        return client

    monkeypatch.setattr(cli, "build_model_client", build, raising=False)
    return record


def _run(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _declare(
    workspace: Path,
    text: str | None,
    *,
    output: str = DECLARATION,
    steps: list[str] | None = None,
    inputs: dict[str, str] | None = None,
    outputs: dict[str, str | None] | None = None,
) -> None:
    """Point `extract` at a field declaration, and write it unless `text` is None.

    No `incident.json` is written: nothing names it any more, and a stale one
    lying beside the declaration would let a loader that still reads JSON find
    a file to succeed on.
    """
    write_pipeline(
        workspace,
        steps=steps or ["extract"],
        inputs=inputs,
        outputs={"extract": output, **(outputs or {})},
        write_schema=False,
    )
    directory = workspace / "pipelines" / PIPELINE
    rubrics = directory / "rubrics"
    rubrics.mkdir(exist_ok=True)
    (rubrics / "root_cause.md").write_text(
        "Is the stated root cause supported by the named document?\n", encoding="utf-8"
    )
    if text is not None:
        (directory / output).write_text(text, encoding="utf-8")


class TestOutputDeclarationsMustLoadAndValidate:
    """R3.10 — a declaration that cannot be scored is found now, not after a run is paid for."""

    def test_a_valid_declaration_gets_the_user_to_a_plan(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Example 1: the one where five fields are declared and every kind exists.

        That its hash then enters the `extract` key is R6.11's claim and is proved
        there. Here the promise is the user's: a sound declaration is not refused.
        """
        _declare(synced, INCIDENT_YAML)

        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert "extract" in result.output
        assert model_calls == []

    def test_a_missing_declaration_names_the_path_and_the_step(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Example 2: the one where `schemas/missing.yaml` is not there."""
        _declare(synced, None, output="schemas/missing.yaml")

        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code != 0
        assert "schemas/missing.yaml" in result.output
        assert "extract" in result.output
        assert model_calls == []

    def test_malformed_yaml_names_the_file_and_the_parse_position(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Example 3: the one where the declaration is there and unreadable.

        The break is on line 3 on purpose. A loader still parsing the file as
        JSON also fails -- but at line 1, where `fields:` begins -- and would
        otherwise pass a check that only looked for the word "line".
        """
        broken = (
            "fields:\n"
            "  loss_amount:      {kind: amount, currency: CHF}\n"
            "  severity:         {kind: enum, values: [minor, major, critical}\n"
        )
        _declare(synced, broken)

        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code != 0
        assert "incident.yaml" in result.output
        assert "line 3" in result.output
        assert model_calls == []

    def test_an_unknown_kind_names_the_field_and_the_kinds_that_exist(
        self, synced: Path, monkeypatch, model_calls
    ):
        """Example 4: the one where `loss_amount` declares a kind nobody can score.

        Listing the five is what turns the error into its own fix: the author
        sees `money` next to `amount` and knows what to write.
        """
        _declare(
            synced,
            "fields:\n"
            "  loss_amount: {kind: money, currency: CHF}\n"
            "  severity:    {kind: enum, values: [minor, major, critical]}\n",
        )

        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code != 0
        assert "loss_amount" in result.output
        for kind in KINDS:
            assert kind in result.output
        assert model_calls == []

    def test_a_step_with_no_output_is_accepted(self, synced: Path, monkeypatch, model_calls):
        """Counter-example (row 5): the one where `report` produces prose.

        No declaration means no declaration check, not a missing-file error --
        and no scoring for that step.
        """
        _declare(
            synced,
            INCIDENT_YAML,
            steps=["extract", "report"],
            inputs={"report": "extract"},
            outputs={"report": None},
        )

        result = _run(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert "report" in result.output
        assert model_calls == []
