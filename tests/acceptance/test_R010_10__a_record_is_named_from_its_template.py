"""R10.10 — a record's name is rendered from the name template for its command.

The experiment says which records are comparable; the name says which one this
is. `eval of <run id>` is filterable and not readable: the thing a person scans a
list for -- which model, which attempt -- was in the params, one click from a
list they would have to open forty times.

Rows 1, 2, 4, 5 and 6 live here, because each is observable by running a command
with an environment a person sets. Row 3's `{a} vs {b}` stays in the unit test:
it is the same claim as row 5 -- an override is read -- over a command that needs
two prior runs to reach, and a second acceptance test of one claim is a second
place for it to rot.

Tracking is switched on the way a person switches it on, in the environment
(R10.1), and after the sync, so the only MLflow run under test is the command
each test names. The CLI is handed a `FakeTracker` through the same seam
`build_model_client` uses; it records the name it was given and sends nothing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.fakes import FakeTracker, NoModelClient, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)

from dossier.application.eval import judge_prompt_hash
from dossier.domain.gold import gold_set_hash
from dossier.domain.hashing import text_hash

pytestmark = pytest.mark.outer_loop

URI = "http://localhost:5000"
GOLD = "gold/incidents"

# The model the scoring example pins, written as `model:` pins it. The whole of
# row 1 is that a name carries it unabbreviated: a shortened identifier is a
# second spelling of the one value whose point is to be exact (R0.6).
MODEL = RoutedModel.model_id


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _calibrate(workspace: Path) -> None:
    """A measured judge, so `root_cause` is reported rather than withheld (R7.15).

    Nothing here is about naming. It is present because an eval of this gold set
    reaches a judged field, and a withheld one prints a different report -- which
    would leave these tests passing for a reason none of them states.
    """
    gold = workspace / "gold" / "incidents"
    (gold / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    (gold / "calibrations").mkdir(exist_ok=True)
    (gold / "calibrations" / "root_cause.json").write_text(
        json.dumps(
            {
                "judge_model": MODEL,
                "rubric_hash": text_hash(
                    workspace / "pipelines" / PIPELINE / "rubrics" / "root_cause.md"
                ),
                "prompt_hash": judge_prompt_hash(),
                "agreement": 1.0,
                "sample_size": 20,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def held(workspace: Path, monkeypatch) -> Path:
    """The four incidents synced, with tracking still off.

    Off on purpose: a sync records too (R11.4), and a tracker switched on before
    it would hold a run every assertion below is not about.
    """
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


@pytest.fixture
def tracker(monkeypatch) -> FakeTracker:
    """Tracking on, recording to a fake that keeps the name it was handed."""
    import dossier.cli.main as cli

    recorder = FakeTracker()
    monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
    monkeypatch.setattr(cli, "build_tracker", lambda settings: recorder, raising=False)
    return recorder


@pytest.fixture
def scored(held: Path, monkeypatch) -> tuple[Path, str]:
    """The run an eval will score, made before tracking is on; its id."""
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))
    ran = _cli(held, monkeypatch, "run", PIPELINE)
    assert ran.exit_code == 0, ran.output
    _calibrate(held)
    found = re.search(r"^run (\S+)", ran.output, re.MULTILINE)
    assert found, ran.output
    return held, found.group(1)


def _eval(workspace: Path, monkeypatch):
    """`dossier eval`, scoring a replay and so asking no model (R7.10)."""
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
    return _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)


class TestARecordIsNamedFromItsTemplate:
    """R10.10 — a record's name is rendered from the name template for its command."""

    def test_an_eval_is_named_for_the_run_it_scored_and_the_model_that_produced_it(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 1: the one where nothing is configured and the default renders.

        Both values are ones the command already holds -- the run it reproduced
        and the model that run pinned -- and neither is abbreviated to fit.
        """
        workspace, run_id = scored

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert len(tracker.runs) == 1, "one eval is one MLflow run"
        assert tracker.runs[0].name == f"eval {run_id} · {MODEL}"

    def test_a_configured_prefix_opens_the_name_with_its_own_separator(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 2: the one where a person wants every record of theirs prefixed.

        The separator belongs to `{prefix}`, not to the template around it. That
        is what lets one variable prefix every kind without six templates being
        rewritten, and what leaves an unset prefix with no stray ` · ` to strip.
        """
        workspace, run_id = scored
        monkeypatch.setenv("DOSSIER_MLFLOW_RUN_PREFIX", "nightly")

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].name == f"nightly · eval {run_id} · {MODEL}"

    def test_a_template_naming_a_placeholder_the_command_cannot_fill_is_refused(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Example 4: the one where a run's template asks for a gold set.

        Refused before any work, naming the variable it came from: rendered
        literally, `{gold}` would open a run nobody meant and records would pile
        up under it unnoticed (R10.2's shape, on the other template).

        The model proves *before any work*. It answers every document in this
        pipeline, and a refusal that arrived late would show up here as a call.
        """
        import dossier.cli.main as cli

        monkeypatch.setenv("DOSSIER_MLFLOW_RUN_NAME_RUN", "{gold} {run_id}")
        model = RoutedModel(ANSWERS)
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 2, result.output
        assert "DOSSIER_MLFLOW_RUN_NAME_RUN" in result.output
        assert "{gold}" in result.output
        assert model.calls == [], "refused before any work, so no document was asked about"
        assert tracker.runs == [], "nothing was named, so nothing was recorded"

    def test_a_hash_in_a_name_is_its_eight_character_display_form(
        self, scored: tuple[Path, str], monkeypatch, tracker: FakeTracker
    ):
        """Example 5: the one where a person names their evals by the answers.

        A name is read by a person, so a hash renders as the eight characters
        every spec displays. The full 64 stay in the tags, where a comparison is
        made (R0.7).
        """
        workspace, _ = scored
        monkeypatch.setenv("DOSSIER_MLFLOW_RUN_NAME_EVAL", "{prefix}eval {gold_hash}")
        files = {
            path.name: path.read_bytes() for path in sorted((workspace / GOLD).glob("*.json"))
        }
        full = gold_set_hash(files)

        result = _eval(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        assert tracker.runs[0].name == f"eval {full[:8]}"
        assert len(full) == 64, "the display form is a prefix of a real hash, not a hash"

    def test_a_run_with_nothing_configured_is_named_exactly_its_run_id(
        self, held: Path, monkeypatch, tracker: FakeTracker
    ):
        """Counter-example (row 6): the one where nobody configured anything.

        Byte-identical to R11.1 row 1. Every name recorded before this rule is
        unchanged until someone sets a variable -- which is the whole of why
        `{prefix}` and `{label}` render empty rather than rendering a separator.
        """
        import dossier.cli.main as cli

        monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))

        result = _cli(held, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        run_id = re.search(r"^run (\S+)", result.output, re.MULTILINE).group(1)
        assert tracker.runs[0].name == run_id
        assert " · " not in tracker.runs[0].name
