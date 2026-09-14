"""R1.10 — a connector declares the keys its sources take, checked at load time.

The keys every source has -- `id`, `type`, `fields`, `convert`,
`watermark_overlap` -- are the core's. Everything else belongs to one type, and
only its connector knows it: a folder has a `path`, a Jira source a `query`. The
loader checks each source against the shared keys plus its connector's
declaration, before anything runs.

`config/` may import only `domain/`, so it cannot reach the connector registry.
The declarations are handed in as a mapping from type to keys model -- the CLI
builds it from the registry, and a test passes one directly.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from dossier.config.load import ConfigError, load_sources
from dossier.infrastructure.connectors.folder import FolderKeys

CONNECTORS = {"folder": FolderKeys}


class SharepointKeys(BaseModel):
    """What a third-party `sharepoint` connector might declare -- nothing dossier knows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestConnectorsDeclareTheirKeys:
    """R1.10 — a type's keys are its connector's, checked before anything runs."""

    def test_a_folder_with_its_path_is_accepted(self, tmp_path: Path):
        """Example 1: the one where `path` is a key the folder connector declares."""
        path = write(
            tmp_path,
            "sources:\n"
            "  - id: incidents-manual\n"
            "    type: folder\n"
            "    path: inbox/incidents/\n",
        )

        (source,) = load_sources(path, connectors=CONNECTORS)

        assert source.options == {"path": "inbox/incidents/"}

    def test_a_misspelt_key_is_answered_from_the_connectors_declaration(self, tmp_path: Path):
        """Example 3: the one where `pth` is refused and `path` suggested.

        The suggestion comes from the folder connector's declaration -- the core
        has no list of a folder's keys to suggest from (R3.1 row 1).
        """
        path = write(
            tmp_path,
            "sources:\n  - id: incidents-manual\n    type: folder\n    pth: inbox/incidents/\n",
        )

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors=CONNECTORS)

        message = str(error.value)
        assert "pth" in message
        assert "'path'" in message

    def test_a_third_party_types_keys_load_and_are_checked(self, tmp_path: Path):
        """Example 4: the one where `sharepoint` brings keys dossier has never heard of.

        Its `site` loads, and its `sitte` is refused with `site` suggested --
        checked exactly as a folder's are, with no edit to dossier (R1.7 row 2).
        """
        connectors = {**CONNECTORS, "sharepoint": SharepointKeys}
        good = write(
            tmp_path, "sources:\n  - id: procedures\n    type: sharepoint\n    site: OPS\n"
        )

        (source,) = load_sources(good, connectors=connectors)

        assert source.options == {"site": "OPS"}

        bad = write(
            tmp_path, "sources:\n  - id: procedures\n    type: sharepoint\n    sitte: OPS\n"
        )
        with pytest.raises(ConfigError) as error:
            load_sources(bad, connectors=connectors)

        assert "'site'" in str(error.value)

    def test_a_type_no_package_provides_is_refused_at_load(self, tmp_path: Path):
        """Example 5: the one where `sharepoint` is written but not installed.

        A source cannot be checked against a declaration that does not exist, so
        it is refused now, naming the types that are available.
        """
        path = write(tmp_path, "sources:\n  - id: procedures\n    type: sharepoint\n")

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors=CONNECTORS)

        message = str(error.value)
        assert "sharepoint" in message
        assert "folder" in message

    def test_watermark_overlap_is_the_cores_to_check_not_the_connectors(self, tmp_path: Path):
        """Counter-example (row 6): the one where `incidents-jira` sets its overlap.

        A shared key every source may carry, so the core reads it as a duration --
        and a connector that declares nothing still accepts it (R2.4).
        """
        path = write(
            tmp_path,
            "sources:\n  - id: incidents-jira\n    type: jira\n    watermark_overlap: 24h\n",
        )

        (source,) = load_sources(path, connectors={"jira": None})

        assert source.watermark_overlap == timedelta(hours=24)
        assert source.options == {}

    def test_a_folder_with_no_path_is_refused_at_load_not_at_the_first_sync(
        self, tmp_path: Path
    ):
        """Example 2: the one where the folder connector's own requirement is found early.

        Today a folder source with no `path` loads, and fails an hour later at
        the first sync. The declaration makes it a load-time error, naming the
        line the source starts on.
        """
        path = write(tmp_path, "sources:\n  - id: incidents-manual\n    type: folder\n")

        with pytest.raises(ConfigError) as error:
            load_sources(path, connectors=CONNECTORS)

        message = str(error.value)
        assert "sources.yaml" in message
        assert "line 2" in message
        assert "'path'" in message
