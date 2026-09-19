"""R7.13 — a judge's agreement threshold is declared with the gold set, never with
the field declaration.

A threshold is a property of scoring. The field declaration is hashed as text
into every stage key that reads it (R6.11), so a bar raised from 0.95 to 0.96
there would re-run every extraction the pipeline has cached -- to change a number
no extraction can affect. The gold set is what the judge is measured against, is
a workspace asset several pipelines may share (R3.7), and is in no key.

`gold/<name>/judge.yaml` holds the thresholds. YAML rather than JSON so it
cannot be read as one of the `<document>.json` files a gold set is made of,
which `load_gold` would otherwise validate as a document.

**R7.13 is superseded by R7.20**, which keeps every claim this file tests and
declares a bar per grounding state rather than one per field. A scalar is still
valid and means the `grounded` bar, so the rows below are unchanged apart from
the shape they read back -- which is the point of keeping the scalar.

The gold files are the person-written set in `tests/fixtures/gold/incidents/`,
copied into a temporary workspace and never written to in place.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_output_schema, load_pipeline

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"

# `write_pipeline`'s declaration, which is spec 006's: `root_cause` is the one
# free-text field, judged against a rubric, and so the one needing a threshold.
JUDGED = "root_cause"


def _workspace(root: Path, *, judge: str | None) -> Path:
    """A pipeline declaring `gold/incidents/`, with `judge.yaml` written or absent."""
    path = write_pipeline(root)
    path.write_text(
        path.read_text(encoding="utf-8") + "gold: gold/incidents/\n", encoding="utf-8"
    )
    gold = root / "gold" / "incidents"
    shutil.copytree(FIXTURE_GOLD, gold)
    if judge is not None:
        (gold / "judge.yaml").write_text(judge, encoding="utf-8")
    return path


def _thresholds(root: Path) -> dict[str, dict[str, float]]:
    """The declared thresholds, read the way `dossier eval` will read them.

    Imported inside the helper rather than at module scope: until this lands,
    collecting the default suite would error on a name that does not exist yet,
    and a red collection is not the same as a red test.
    """
    from dossier.config.load import load_judge_thresholds

    return load_judge_thresholds(root / "gold" / "incidents")


def _declaration(root: Path) -> Path:
    return root / "pipelines" / "incident-audit" / "schemas" / "incident.yaml"


class TestAJudgeThresholdIsDeclaredWithTheGoldSet:
    """R7.13 — the bar lives with the gold set, and is a proportion."""

    def test_a_threshold_declared_with_the_gold_set_is_the_one_eval_gates_on(
        self, tmp_path: Path
    ):
        """Example 1: the one where `judge.yaml` declares `root_cause: 0.95`."""
        path = _workspace(tmp_path, judge=f"{JUDGED}: 0.95\n")

        config = load_pipeline(path, providers=PROVIDERS)

        assert config.gold == "gold/incidents/"
        assert _thresholds(tmp_path) == {JUDGED: {"grounded": 0.95}}

    def test_a_judged_field_with_no_threshold_is_refused_naming_it_and_the_file(
        self, tmp_path: Path
    ):
        """Example 2: the one whose `judge.yaml` says nothing about `root_cause`.

        A judged field with no bar would be reported as though it had cleared
        one, which is the whole failure R7.5 exists to prevent. Named with the
        file, because that is where the fix goes.
        """
        path = _workspace(tmp_path, judge="loss_amount: 0.9\n")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert JUDGED in str(error.value)
        assert "judge.yaml" in str(error.value)

    def test_a_threshold_written_as_a_percentage_is_refused(self, tmp_path: Path):
        """Example 3: the one declaring `95` where it means `0.95`.

        Agreement is a proportion. `95` would make every judge ineligible
        forever while reading like strict configuration rather than a typo --
        the same reasoning `is_eligible` refuses it on (R7.5).
        """
        path = _workspace(tmp_path, judge=f"{JUDGED}: 95\n")

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert JUDGED in str(error.value)
        assert "95" in str(error.value)

    def test_changing_a_threshold_moves_no_stage_key(self, tmp_path: Path):
        """Counter-example (row 4): the one where the bar moves and nothing re-runs.

        This is the reason the threshold is not in the field declaration. Both
        hashes that reach a stage key come from the declaration -- its own text
        (R6.11) and the schema generated from it (R6.12) -- and neither may
        notice a threshold at all. If someone later moves the bar into the
        declaration to keep it near the rubric, this is the test that objects.
        """
        path = _workspace(tmp_path, judge=f"{JUDGED}: 0.95\n")
        load_pipeline(path, providers=PROVIDERS)
        before = load_output_schema(_declaration(tmp_path))

        (tmp_path / "gold" / "incidents" / "judge.yaml").write_text(
            f"{JUDGED}: 0.96\n", encoding="utf-8"
        )
        load_pipeline(path, providers=PROVIDERS)
        after = load_output_schema(_declaration(tmp_path))

        assert _thresholds(tmp_path) == {JUDGED: {"grounded": 0.96}}
        assert after.declaration_hash == before.declaration_hash
        assert after.generated_schema_hash == before.generated_schema_hash
