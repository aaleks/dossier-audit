"""R3.7 — a pipeline declaring `gold` must point at a directory that exists and
conforms to spec 007.

A pipeline whose gold set cannot be read is one whose run cannot be scored, and
finding that out after the run has been paid for is the failure load-time checks
exist to prevent (R3.8's reasoning). `gold` is resolved against the workspace --
where `dossier` runs, and where `dossier eval --gold` resolves the same path --
not against the pipeline's own directory.

The gold files are the person-written set in `tests/fixtures/gold/incidents/`,
copied into a temporary workspace and never written to in place.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_pipeline

FIXTURE_GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "gold" / "incidents"


def _pipeline(workspace: Path, gold: str | None) -> Path:
    path = write_pipeline(workspace)
    if gold is not None:
        path.write_text(path.read_text(encoding="utf-8") + f"gold: {gold}\n", encoding="utf-8")
    return path


def _gold_set(workspace: Path) -> Path:
    """The person-written gold set, at `gold/incidents/` in this workspace.

    `judge.yaml` is written into the copy rather than shipped in the fixture:
    the declaration these pipelines use judges `root_cause` against a rubric, and
    a judged field with no declared threshold is refused at load time (R7.13). It
    belongs to the copy because the committed gold set is human-owned -- what
    counts as a verified answer is not something a test may edit.
    """
    destination = workspace / "gold" / "incidents"
    shutil.copytree(FIXTURE_GOLD, destination)
    (destination / "judge.yaml").write_text("root_cause: 0.95\n", encoding="utf-8")
    return destination


class TestGoldDirectoryIsValidatedAtLoadTime:
    """R3.7 — a declared gold set exists and conforms to spec 007, or nothing loads."""

    def test_a_gold_set_holding_one_valid_file_per_document_is_accepted(self, tmp_path: Path):
        """Example 1: the one pointing at `gold/incidents/` in the workspace.

        The set sits at the workspace root, not under `pipelines/incident-audit/`,
        so this is also the row that fails if `gold` were read against the
        pipeline's own directory.
        """
        _gold_set(tmp_path)

        config = load_pipeline(_pipeline(tmp_path, "gold/incidents/"), providers=PROVIDERS)

        assert config.gold == "gold/incidents/"

    def test_a_gold_directory_that_does_not_exist_is_refused_naming_it(self, tmp_path: Path):
        """Example 2: the one whose `gold/incidents/` was never created."""
        with pytest.raises(ConfigError) as error:
            load_pipeline(_pipeline(tmp_path, "gold/incidents/"), providers=PROVIDERS)

        assert "gold/incidents" in str(error.value)

    def test_a_gold_file_missing_verified_by_is_refused_naming_the_file_and_the_key(
        self, tmp_path: Path
    ):
        """Example 3: the one where `INC-4821.json` says nobody verified it.

        There is no anonymous path into the gold set (R7.7); an unattributed
        answer is found before anything is scored against it.
        """
        gold = _gold_set(tmp_path)
        unattributed = json.loads((gold / "INC-4821.json").read_text(encoding="utf-8"))
        del unattributed["verified_by"]
        (gold / "INC-4821.json").write_text(json.dumps(unattributed), encoding="utf-8")

        with pytest.raises(ConfigError) as error:
            load_pipeline(_pipeline(tmp_path, "gold/incidents/"), providers=PROVIDERS)

        assert "INC-4821.json" in str(error.value)
        assert "verified_by" in str(error.value)

    def test_a_pipeline_with_no_gold_key_is_accepted(self, tmp_path: Path):
        """Counter-example (row 4): the one that declares no gold set at all.

        `dossier run` works without one; only `dossier eval` needs a gold set.
        """
        config = load_pipeline(_pipeline(tmp_path, None), providers=PROVIDERS)

        assert config.gold is None
