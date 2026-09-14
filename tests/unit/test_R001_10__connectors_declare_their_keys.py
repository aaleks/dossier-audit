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

from pathlib import Path

import pytest

from dossier.config.load import ConfigError, load_sources
from dossier.infrastructure.connectors.folder import FolderKeys

CONNECTORS = {"folder": FolderKeys}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestConnectorsDeclareTheirKeys:
    """R1.10 — a type's keys are its connector's, checked before anything runs."""

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
