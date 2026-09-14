"""R3.1 — an invalid configuration file fails at load time, naming file, line and key.

A schema error that says only "validation failed" costs more than the error it
reports: the person reading it has to find the key the loader already found.
So the message says where, and -- for a misspelt key -- what was probably meant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.config.load import ConfigError, load_sources
from dossier.infrastructure.connectors.folder import FolderKeys


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
            load_sources(path, connectors={"folder": FolderKeys})

        message = str(error.value)
        assert "sources.yaml" in message
        assert "line 4" in message
        assert "pth" in message
        assert "'path'" in message

    def test_a_missing_required_key_is_named(self, tmp_path: Path):
        """Example 2: the one where a folder source has no `path`.

        Required by the folder connector, not by the core (R1.10 row 2) -- named
        all the same, at the line its source starts on.
        """
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n  - id: incidents-manual\n    type: folder\n", encoding="utf-8"
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"folder": FolderKeys})

        message = str(error.value)
        assert "sources.yaml" in message
        assert "line 2" in message
        assert "'path'" in message

    def test_a_bare_number_where_a_duration_belongs_is_a_type_error(self, tmp_path: Path):
        """Example 3: the one where `watermark_overlap: 24` could mean hours or seconds.

        The field is a duration such as `24h`. A bare number is refused rather
        than guessed at, and -- like any other invalid key -- named at its line.
        """
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - id: incidents-manual\n"
            "    type: folder\n"
            "    path: inbox/incidents/\n"
            "    watermark_overlap: 24\n",
            encoding="utf-8",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors={"folder": FolderKeys})

        message = str(error.value)
        assert "sources.yaml" in message
        assert "line 5" in message
        assert "watermark_overlap" in message
        assert "24h" in message

    def test_keys_in_an_unusual_order_are_accepted(self, tmp_path: Path):
        """Counter-example (row 4): the one where `path` comes before `id`.

        Key order in YAML carries no meaning, so it is not an error.
        """
        path = tmp_path / "sources.yaml"
        path.write_text(
            "sources:\n"
            "  - path: inbox/incidents/\n"
            "    type: folder\n"
            "    id: incidents-manual\n",
            encoding="utf-8",
        )

        (source,) = load_sources(path, connectors={"folder": FolderKeys})

        assert source.id == "incidents-manual"
        assert source.options == {"path": "inbox/incidents/"}
