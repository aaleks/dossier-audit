"""R3.2 — a step id is unique within a pipeline and matches `[a-z][a-z0-9_]*`.

Step ids become directory names and appear in cache keys, so they must be stable
and unambiguous.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_pipeline


class TestStepIds:
    """R3.2 — an id that cannot be a directory name cannot be a step."""

    def test_ordinary_ids_are_accepted(self, tmp_path: Path):
        """Example 1: the one from the design deck."""
        path = write_pipeline(tmp_path, steps=["extract", "verify", "report"])

        assert [step.id for step in load_pipeline(path, providers=PROVIDERS).steps] == [
            "extract",
            "verify",
            "report",
        ]

    def test_a_duplicate_id_is_rejected(self, tmp_path: Path):
        """Example 2: the one where two steps would share a directory."""
        path = write_pipeline(tmp_path, steps=["extract", "verify", "verify"])

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert "verify" in str(error.value)

    @pytest.mark.parametrize(
        "step_id",
        [
            pytest.param("Verify-2", id="uppercase-and-hyphen"),
            pytest.param("2extract", id="leading-digit"),
            pytest.param("_extract", id="leading-underscore"),
            pytest.param("extract step", id="space"),
            pytest.param("", id="empty"),
        ],
    )
    def test_a_malformed_id_is_rejected(self, tmp_path: Path, step_id: str):
        """Example 3: the one where the shape is wrong.

        Uppercase matters more than it looks: step ids become directory names,
        and a filesystem that case-folds would make `Verify` and `verify` the
        same directory on one machine and two on another (R5.6).
        """
        path = write_pipeline(tmp_path, steps=[step_id])

        with pytest.raises(ConfigError):
            load_pipeline(path, providers=PROVIDERS)

    def test_digits_and_underscores_are_allowed_after_the_first_character(self, tmp_path: Path):
        """Counter-example (row 4): the one where `verify_2` is fine."""
        path = write_pipeline(tmp_path, steps=["verify_2"])

        config = load_pipeline(path, providers=PROVIDERS)

        assert [step.id for step in config.steps] == ["verify_2"]
