"""R3.5 — every `output` path resolves to a schema file that itself loads.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

from dossier.config.load import ConfigError, load_pipeline


class TestOutputSchemas:
    """R3.5 — a schema that cannot be read is found now, not mid-run."""

    def test_a_present_and_valid_schema_is_accepted(self, tmp_path: Path):
        """Example 1: the one where everything is where it says it is."""
        path = write_pipeline(tmp_path, steps=["extract"])

        assert load_pipeline(path).steps[0].output == "schemas/incident.json"

    def test_a_missing_schema_names_the_path_and_the_step(self, tmp_path: Path):
        """Example 2: the one where the file is not there."""
        path = write_pipeline(tmp_path, steps=["extract"], write_schema=False)

        with pytest.raises(ConfigError) as error:
            load_pipeline(path)

        message = str(error.value)
        assert "extract" in message
        assert "schemas/incident.json" in message

    def test_malformed_json_names_the_file_and_the_position(self, tmp_path: Path):
        """Example 3: the one where the schema is there and unreadable.

        The position matters: a JSON schema is long, and "invalid JSON" without a
        line number means reading all of it.
        """
        path = write_pipeline(tmp_path, steps=["extract"], schema_text='{"type": }')

        with pytest.raises(ConfigError) as error:
            load_pipeline(path)

        message = str(error.value)
        assert "incident.json" in message
        assert "line" in message and "column" in message

    def test_a_step_with_no_output_is_accepted(self, tmp_path: Path):
        """Counter-example (row 4): the one where `report` produces prose.

        An `aggregate` step may have no schema at all, and no schema means no
        schema check rather than a missing-file error.
        """
        path = write_pipeline(tmp_path, steps=["extract", "report"], outputs={"report": None})

        assert load_pipeline(path).steps[1].output is None

    def test_a_schema_path_is_resolved_against_the_pipeline_directory(self, tmp_path: Path):
        """The one that makes a pipeline movable.

        Relative to the pipeline, not the working directory, so `dossier sync`
        works the same whichever directory it is invoked from -- and so a
        pipeline can be copied somewhere else intact.
        """
        path = write_pipeline(tmp_path, steps=["extract"])

        assert load_pipeline(path).steps[0].output == "schemas/incident.json"
        assert (path.parent / "schemas" / "incident.json").exists()
