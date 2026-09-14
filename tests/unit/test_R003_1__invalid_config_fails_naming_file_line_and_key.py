"""R3.1 — an invalid configuration file fails at load time, naming file, line and key.

A schema error that says only "validation failed" costs more than the error it
reports: the person reading it has to find the key the loader already found.
So the message says where, and -- for a misspelt key -- what was probably meant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.config.load import ConfigError, load_sources


class TestInvalidConfigFailsNamingFileLineAndKey:
    """R3.1 — the message names the file, the line and the key."""

    def test_a_misspelt_key_is_named_where_it_is_and_the_right_one_suggested(
        self, tmp_path: Path
    ):
        """Example 1: the one where `pth` was meant to be `path`.

        `pth` is on line 4, so the message can be held to exactly that line.
        """
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n  - id: incidents-manual\n    type: folder\n    pth: inbox/incidents/\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path)

        message = str(error.value)
        assert "sources.yaml" in message
        assert "line 4" in message
        assert "pth" in message
        assert "'path'" in message
