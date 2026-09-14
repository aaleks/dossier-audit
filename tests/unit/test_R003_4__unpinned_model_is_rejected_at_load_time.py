"""R3.4 — a model value that is not fully version-pinned is rejected at load time.

The load-time half of R0.6. A floating alias is one a provider may re-point, so
a run keyed on it could be answered by a different model next month under the
same key -- and nothing in the cache would say so. Refused before anything runs,
naming where it was written, because the fix is one line in one file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_pipeline

ALIAS = "anthropic:claude-sonnet-4-5"
PINNED = "anthropic:claude-sonnet-4-5-20250929"


class TestUnpinnedModelIsRejectedAtLoadTime:
    """R3.4 — a model that names no exact version is found now, not after a run."""

    def test_a_dated_snapshot_is_accepted(self, tmp_path: Path):
        """Example 1: the one where the model is exactly one snapshot, and stays one.

        Without this, a check that refused every model would pass the rest of
        this file.
        """
        path = write_pipeline(tmp_path, model=PINNED)

        assert load_pipeline(path, providers=PROVIDERS).model == PINNED

    def test_a_pipeline_with_no_model_is_refused(self, tmp_path: Path):
        """Example 3: the one where `model:` is missing, and nothing fills it in.

        There is no default model. A default would be a choice the author never
        made, keyed into every stage as if they had.
        """
        path = write_pipeline(tmp_path, model=PINNED)
        path.write_text(
            path.read_text(encoding="utf-8").replace(f"model: {PINNED}\n", ""),
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        message = str(error.value)
        assert "pipeline.yaml" in message
        assert "model" in message

    def test_planning_refuses_it_too_though_a_plan_asks_no_model(
        self, workspace: Path, monkeypatch
    ):
        """Counter-example (row 4): the one where `--plan` would never call the model.

        Validity does not depend on whether the model is used (R4.6). A plan
        that accepted an alias would preview a run that could not be started --
        or worse, one keyed on whatever the alias points at today.
        """
        from typer.testing import CliRunner

        from dossier.cli.main import app

        write_pipeline(workspace, model=ALIAS)
        monkeypatch.chdir(workspace)

        result = CliRunner().invoke(app, ["run", "incident-audit", "--plan"])

        assert result.exit_code != 0
        assert ALIAS in result.output

    def test_a_floating_alias_is_refused_naming_the_file_the_line_and_the_alias(
        self, tmp_path: Path
    ):
        """Example 2: the one where `anthropic:claude-sonnet-4-5` could mean any snapshot.

        `write_pipeline` puts `model:` on line 2, so the message can be held to
        naming exactly that line.
        """
        path = write_pipeline(tmp_path, model=ALIAS)

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        message = str(error.value)
        assert "pipeline.yaml" in message
        assert "line 2" in message
        assert ALIAS in message
