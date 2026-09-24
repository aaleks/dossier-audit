"""R8.13 — `converters:` in `sources.yaml` is where a workspace names who answers a pair.

The decision itself is `answering`'s and is proved in
`test_R008_13__a_named_converter_answers_the_pairs_it_claims.py`. What is proved
here is the half that reads the file: the names arrive as written, a file that
names nothing names nothing, and a value that is not a list of names is refused
where it is written rather than read as some other choice (R3.1's shape).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dossier.config.load import ConfigError, load_converter_names

SOURCES = "sources:\n  - id: incidents-manual\n    type: folder\n    path: incidents/\n"


def _sources_yaml(tmp_path: Path, head: str) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(head + SOURCES, encoding="utf-8")
    return path


class TestSourcesYamlNamesTheConvertersThatAnswer:
    """R8.13 — the names a workspace wrote are the names `answering` is handed."""

    def test_the_named_converters_are_read_as_written(self, tmp_path: Path):
        """Row 2: the one where the workspace names Docling."""
        path = _sources_yaml(tmp_path, "converters: [docling-markdown]\n\n")

        assert load_converter_names(path) == ["docling-markdown"]

    def test_a_workspace_naming_nothing_names_no_converter(self, tmp_path: Path):
        """Counter-example, row 1: the one where `sources.yaml` is as it always was."""
        path = _sources_yaml(tmp_path, "")

        assert load_converter_names(path) == []

    def test_a_single_name_not_in_a_list_is_refused_where_it_is_written(self, tmp_path: Path):
        """The one where `converters: docling-markdown` is written without brackets.

        Read as a string, it would be iterated into seventeen one-letter names
        and refused for all of them; refusing the shape names what to write.
        """
        path = _sources_yaml(tmp_path, "converters: docling-markdown\n\n")

        with pytest.raises(ConfigError) as error:
            load_converter_names(path)

        message = str(error.value)
        assert "sources.yaml" in message and "line 1" in message, message
        assert "converters: [docling-markdown]" in message, message

    def test_a_name_that_is_not_text_is_refused(self, tmp_path: Path):
        """The one where the list holds a number."""
        path = _sources_yaml(tmp_path, "converters: [docling-markdown, 3]\n\n")

        with pytest.raises(ConfigError, match="converters"):
            load_converter_names(path)
