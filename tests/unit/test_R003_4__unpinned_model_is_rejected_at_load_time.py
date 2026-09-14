"""R3.4 — a model value that is not fully version-pinned is rejected at load time.

The load-time half of R0.6. A floating alias is one a provider may re-point, so
a run keyed on it could be answered by a different model next month under the
same key -- and nothing in the cache would say so. Refused before anything runs,
naming where it was written, because the fix is one line in one file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

from dossier.config.load import ConfigError, load_pipeline

ALIAS = "anthropic:claude-sonnet-4-5"


class TestUnpinnedModelIsRejectedAtLoadTime:
    """R3.4 — a model that names no exact version is found now, not after a run."""

    def test_a_floating_alias_is_refused_naming_the_file_the_line_and_the_alias(
        self, tmp_path: Path
    ):
        """Example 2: the one where `anthropic:claude-sonnet-4-5` could mean any snapshot.

        `write_pipeline` puts `model:` on line 2, so the message can be held to
        naming exactly that line.
        """
        path = write_pipeline(tmp_path, model=ALIAS)

        with pytest.raises(ConfigError) as error:
            load_pipeline(path)

        message = str(error.value)
        assert "pipeline.yaml" in message
        assert "line 2" in message
        assert ALIAS in message
