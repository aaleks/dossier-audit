"""R3.9 — `fields` is optional, and an empty `fields` list is rejected.

Omitting `fields` selects raw-payload hashing (R2.10). Declaring it empty selects
a projection onto no fields, which is never what anyone means.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.config.load import ConfigError, load_sources

FOLDER_SOURCE = """
sources:
  - id: incidents-manual
    type: folder
    path: inbox/incidents/
"""

WITH_FIELDS = """
sources:
  - id: incidents-jira
    type: jira
    fields: [key, summary, status]
"""

EMPTY_FIELDS = """
sources:
  - id: incidents-jira
    type: jira
    fields: []
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestFieldsIsOptional:
    """R3.9 — absence is meaningful, emptiness is a mistake."""

    def test_a_source_may_declare_no_fields(self, tmp_path: Path):
        """Example 1: the one where a folder source hashes what it is given."""
        (source,) = load_sources(write(tmp_path, FOLDER_SOURCE))

        assert source.id == "incidents-manual"
        assert source.fields is None

    def test_a_source_may_declare_fields(self, tmp_path: Path):
        """Example 2: the one where the projection is configured."""
        (source,) = load_sources(write(tmp_path, WITH_FIELDS))

        assert source.fields == ["key", "summary", "status"]

    def test_an_empty_fields_list_is_rejected(self, tmp_path: Path):
        """Example 3: the one where `[]` is not `absent`.

        A projection onto nothing matches no payload. Read as "hash everything"
        it would hand a source the exact opposite of what it declared (R2.10).
        """
        with pytest.raises(ConfigError) as error:
            load_sources(write(tmp_path, EMPTY_FIELDS))

        message = str(error.value)
        assert "sources.yaml" in message
        assert "incidents-jira" in message

    def test_absent_and_empty_reach_normalisation_differently(self, tmp_path: Path):
        """The one that ties the config rule to the behaviour it selects.

        R3.9 exists to protect R2.10. Asserting the two agree keeps the pair
        honest: absent means hash-as-received, and empty never gets that far.
        """
        from dossier.domain.sync import normalise

        (source,) = load_sources(write(tmp_path, FOLDER_SOURCE))

        assert normalise(b"raw bytes", fields=source.fields) == b"raw bytes"


class TestLoadingTouchesNothingExternal:
    """R3.8 — loading is a pure function of files on disk."""

    def test_loading_makes_no_network_call(self, tmp_path: Path):
        """R3.8 example 1: the one where config is read with the network gone.

        The autouse `no_network` fixture already blocks sockets for this test, so
        a load that reached out would fail here rather than in production.
        """
        assert load_sources(write(tmp_path, FOLDER_SOURCE))

    def test_loading_a_jira_source_does_not_need_its_credentials(self, tmp_path: Path):
        """R3.8 example 3: the one where `JIRA_TOKEN` is nowhere to be seen.

        Credentials are checked when a connector is used, not when config is
        read. The autouse `clean_env` fixture has already removed them.
        """
        assert load_sources(write(tmp_path, WITH_FIELDS))

    def test_a_missing_file_names_itself(self, tmp_path: Path):
        """The one where the error is actionable rather than a traceback."""
        with pytest.raises(ConfigError) as error:
            load_sources(tmp_path / "sources.yaml")

        assert "sources.yaml" in str(error.value)

    def test_malformed_yaml_names_the_file(self, tmp_path: Path):
        """The one where a tab in the wrong place is explained, not dumped."""
        with pytest.raises(ConfigError) as error:
            load_sources(write(tmp_path, "sources: [unclosed\n"))

        assert "sources.yaml" in str(error.value)

    def test_a_duplicate_source_id_is_rejected(self, tmp_path: Path):
        """The one where two sources would fight over one set of ledger rows.

        Not in R3.9's table, but the ledger is keyed by (source_id, key) and two
        sources sharing an id would silently interleave their rows.
        """
        with pytest.raises(ConfigError):
            load_sources(write(tmp_path, FOLDER_SOURCE + FOLDER_SOURCE.split("sources:")[1]))
