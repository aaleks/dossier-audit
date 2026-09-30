"""R3.3 — a step may only reference an id that exists and appears before it.

Forward and self references are the two ways a linear pipeline stops being
linear, and both are cheap to reject.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.config.load import ConfigError, load_pipeline


class TestStepReferences:
    """R3.3 — the graph is a line, and stays one."""

    def test_a_step_may_read_an_earlier_step(self, tmp_path: Path):
        """Example 1: the one where `verify` reads `extract`."""
        path = write_pipeline(
            tmp_path,
            steps=["extract", "verify"],
            inputs={"verify": "[documents, extract]"},
        )

        config = load_pipeline(path, providers=PROVIDERS)

        assert config.steps[1].inputs == ["documents", "extract"]

    @pytest.mark.parametrize("sugar", ["previous", "previous(1)", "previous(2)"])
    def test_relative_sugar_survives_loading(self, tmp_path: Path, sugar: str):
        """Example 5: the one where `previous` is not an id and is left alone.

        Spec 003 lists `previous` and `previous(n)` as legal input values; spec
        004 exists to expand them. Rejecting them here as unknown ids would make
        every rule in 004 unreachable through the CLI, because no pipeline using
        the sugar could ever be loaded.

        Whether the sugar has a predecessor to point at is a different question,
        asked at resolution by R4.3. `previous(2)` on the second step is wrong,
        but it is not wrong *here* -- this layer has no answer to give.
        """
        path = write_pipeline(tmp_path, steps=["extract", "verify"], inputs={"verify": sugar})

        assert load_pipeline(path, providers=PROVIDERS).steps[1].inputs == [sugar]

    def test_sugar_mixed_with_a_keyword_survives_loading(self, tmp_path: Path):
        """Example 5, mixed: the one R4.2 example 3 depends on being loadable."""
        path = write_pipeline(
            tmp_path,
            steps=["extract", "verify"],
            inputs={"verify": "[documents, previous]"},
        )

        config = load_pipeline(path, providers=PROVIDERS)

        assert config.steps[1].inputs == ["documents", "previous"]

    def test_a_step_may_not_read_a_later_step(self, tmp_path: Path):
        """Example 2: the one where `extract` reads `verify`."""
        path = write_pipeline(
            tmp_path, steps=["extract", "verify"], inputs={"extract": "verify"}
        )

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert "verify" in str(error.value)

    def test_a_step_may_not_read_an_id_that_does_not_exist(self, tmp_path: Path):
        """Example 3: the one where `enrich` was never declared."""
        path = write_pipeline(
            tmp_path, steps=["extract", "report"], inputs={"report": "enrich"}
        )

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert "enrich" in str(error.value)

    def test_an_unknown_id_after_the_sugar_is_still_refused(self, tmp_path: Path):
        """Example 6: the one where `enrich` follows `previous`."""
        path = write_pipeline(
            tmp_path, steps=["extract", "verify"], inputs={"verify": "[previous, enrich]"}
        )

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        assert "enrich" in str(error.value)

    def test_a_step_may_not_read_itself(self, tmp_path: Path):
        """The one the check's ordering makes impossible.

        A step id becomes available only after its own inputs are validated, so a
        self-reference is an error rather than a silent no-op that would deadlock
        or read an empty directory at run time.
        """
        path = write_pipeline(tmp_path, steps=["extract"], inputs={"extract": "extract"})

        with pytest.raises(ConfigError):
            load_pipeline(path, providers=PROVIDERS)

    @pytest.mark.parametrize("keyword", ["documents", "reference"])
    def test_source_keywords_are_always_available(self, tmp_path: Path, keyword: str):
        """Counter-example (row 4): the one where the name is not a step id.

        `documents` and `reference` name sources. No step produces them, and a
        first step reading one is entirely ordinary. The pipeline declares a
        reference source, as one reading `reference` must (R3.18 row 4).
        """
        path = write_pipeline(
            tmp_path,
            steps=["extract"],
            inputs={"extract": keyword},
            reference=["procedures-confluence"],
        )

        assert load_pipeline(path, providers=PROVIDERS).steps[0].inputs == [keyword]

    def test_the_error_lists_what_was_available(self, tmp_path: Path):
        """The one where the message is actionable rather than merely correct.

        R3.1 makes an error message an interface. "enrich is not available" sends
        someone to check their spelling; listing what *was* available shows them
        they put the step in the wrong order.
        """
        path = write_pipeline(
            tmp_path,
            steps=["extract", "verify", "report"],
            inputs={"report": "enrich"},
        )

        with pytest.raises(ConfigError) as error:
            load_pipeline(path, providers=PROVIDERS)

        message = str(error.value)
        assert "extract" in message and "verify" in message
