"""R3.18 row 4 — a step reading `reference` in a pipeline that declares no
`reference:` is refused when the pipeline loads.

`{{reference}}` holds every reference document (R3.18). With none declared it
would hold nothing, and the prompt around it would still call that nothing the
procedure to check against. So the pipeline is refused before any work, as a
step reading a kind nothing makes is (R4.13). A pure decision about the
configuration, taken where R3.3's other refusals are.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_pipeline

VERIFYING = "[documents, extract, reference]"
VERIFY = {"steps": ["extract", "verify"], "inputs": {"verify": VERIFYING}}


class TestReadingReferenceNeedsAReferenceSource:
    """R3.18 row 4 — no context declared, so none to read."""

    def test_a_step_reading_reference_with_none_declared_is_refused(self, tmp_path: Path):
        """The one where the pipeline declares no `reference:` at all."""
        path = write_pipeline(tmp_path, **VERIFY)

        with pytest.raises(ConfigError) as refused:
            load_pipeline(path, providers=PROVIDERS)

        assert "'verify'" in str(refused.value)
        assert "reference:" in str(refused.value)

    def test_a_step_reading_reference_with_a_source_declared_loads(self, tmp_path: Path):
        """The counter-example: the one where `procedures-confluence` is declared."""
        path = write_pipeline(tmp_path, **VERIFY, reference=["procedures-confluence"])

        loaded = load_pipeline(path, providers=PROVIDERS)

        assert loaded.steps[1].inputs == ["documents", "extract", "reference"]
