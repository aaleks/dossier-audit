"""R0.11 — a completed `dossier run` writes each artifact a step produced or served
to `runs/<run_id>/<step>/<document>.json`, the same bytes the cache holds.

The naming half of the rule, as a pure decision: what a step's artifact for a
document is called under the run directory. The write itself is proved through
the CLI by the acceptance test; this is the function it names files with.
"""

from __future__ import annotations

import pytest


class TestOutputPathIsTheKeyWithAnExtensionAppended:
    """R0.11 — `<step>/<document>.json`, the key with `.json` appended."""

    @pytest.mark.parametrize(
        ("step", "document", "expected"),
        [
            # The issue key of a Jira source: the form every spec example uses.
            ("extract", "INC-4821", "extract/INC-4821.json"),
            # The file name of a folder source. Appended, never replaced: replacing
            # the suffix would collide `PLAY-1001.md` with `PLAY-1001.pdf`, which
            # R4.10 says are two documents.
            ("extract", "PLAY-1001.md", "extract/PLAY-1001.md.json"),
        ],
    )
    def test_a_structured_artifact_is_the_key_plus_json(self, step, document, expected):
        """The one where the artifact under `runs/` is the key with `.json` appended."""
        from dossier.domain.store import output_path

        assert output_path(step, document, structured=True) == expected

    def test_a_text_artifact_is_the_key_plus_md(self):
        """The one where `report` declares no output, so its artifact is text (row 5)."""
        from dossier.domain.store import output_path

        assert output_path("report", "INC-4821", structured=False) == "report/INC-4821.md"
