"""R18.10 — an index declaration is refused at load when a field is undeclared, a
filter is free text, an embedded field is a category, or the model is not pinned.

`indexes/<name>.yaml` names the fields of its pipeline's output it carries, and
they are checked against that output's declaration when the index is loaded,
before anything is embedded: a field the run never answers is a column that is
never filled, and found only by someone wondering why a filter returns nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.pipelines import PROVIDERS, write_pipeline

from dossier.domain.pipeline import SourceConfig

PIPELINE = "incident-audit"
MODEL = (
    "ollama:qwen3-embedding:4b-fp16"
    "@sha256:3c93b6415795f9cc3e16c403a492ce25b1c0e260f2f760acc90e2035de25f9bc"
)
TAXONOMY = """\
fields:
  failure_category:             {kind: enum, values: [certificate-expiry, capacity-exhaustion]}
  component:                    {kind: enum, values: [checkout, payments-api]}
  root_cause_category:          {kind: enum, values: [process-gap, code-defect]}
  contributing_factor_category: {kind: enum, values: [alert-routing, change-freeze]}
  architecture_category:        {kind: enum, values: [load-balancer-config, single-region]}
  root_cause:                   {kind: free_text, judge: rubrics/root_cause.md}
"""
# The source `write_pipeline` reads, with its readers declared (R18.6).
READ = [SourceConfig(id="incidents-manual", type="folder", acl=["incident-response"])]
SPEC_FIELDS = (
    "fields:\n"
    "  filter: [failure_category, component, root_cause_category,"
    " contributing_factor_category, architecture_category]\n"
    "  embed: [root_cause]\n"
)


def declaration(*, model: str = MODEL, fields: str = "") -> str:
    return (
        f"pipeline: {PIPELINE}\n"
        f"embedding_model: {model}\n"
        "chunker: {name: headings, max_chars: 2000}\n"
        f"{fields}"
        "target: {dsn_env: DOSSIER_INDEX_DSN}\n"
    )


def load(workspace: Path, text: str):
    from dossier.config.load import load_index

    path = workspace / "indexes" / "incidents.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return load_index(path, providers=PROVIDERS, sources=READ)


def refusal(workspace: Path, text: str) -> str:
    from dossier.config.load import ConfigError

    with pytest.raises(ConfigError) as refused:
        load(workspace, text)
    return str(refused.value)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """`incident-audit`, whose one step declares the five fields of spec 006."""
    write_pipeline(tmp_path)
    return tmp_path


class TestAnIndexDeclarationIsCheckedAtLoad:
    """R18.10 — refused at load, naming what is wrong and where."""

    def test_a_field_the_output_does_not_declare_is_refused(self, workspace: Path):
        """Row 1 — the one misspelling `failure_category`."""
        said = refusal(workspace, declaration(fields="fields:\n  filter: [failure_categroy]\n"))

        assert said == (
            "incidents.yaml, line 5: fields.filter names 'failure_categroy', which "
            "schemas/incident.yaml does not declare. It declares: affected_systems, "
            "loss_amount, resolution_date, root_cause, severity"
        )

    def test_a_free_text_field_is_not_a_filter(self, workspace: Path):
        """Row 2 — the one filtering on `root_cause`."""
        said = refusal(workspace, declaration(fields="fields:\n  filter: [root_cause]\n"))

        assert said == (
            "incidents.yaml, line 5: fields.filter names 'root_cause', a free_text "
            "field: free text is embedded, not filtered"
        )

    def test_a_category_is_not_embedded(self, workspace: Path):
        """Row 3 — the one embedding `severity`."""
        said = refusal(workspace, declaration(fields="fields:\n  embed: [severity]\n"))

        assert said == (
            "incidents.yaml, line 5: fields.embed names 'severity', an enum field: "
            "a category is filtered, not embedded"
        )

    def test_an_ollama_tag_with_no_digest_is_refused(self, workspace: Path):
        """Row 4 — the one pinning `qwen3-embedding:4b-fp16` by its tag alone (R9.3)."""
        said = refusal(workspace, declaration(model="ollama:qwen3-embedding:4b-fp16"))

        assert said.startswith(
            "incidents.yaml, line 2: embedding_model 'ollama:qwen3-embedding:4b-fp16' "
            "is an Ollama tag with no digest"
        ), said

    def test_the_declaration_this_spec_writes_loads(self, tmp_path: Path):
        """Row 5, counter-example — the one spec 018 writes, over a taxonomy."""
        write_pipeline(tmp_path, outputs={"extract": "schemas/taxonomy.yaml"})
        schema = tmp_path / "pipelines" / PIPELINE / "schemas" / "taxonomy.yaml"
        schema.write_text(TAXONOMY, encoding="utf-8")

        index = load(tmp_path, declaration(fields=SPEC_FIELDS))

        assert index.name == "incidents"
        assert index.pipeline == PIPELINE
        assert index.embedding_model == MODEL
        assert index.chunker.max_chars == 2000
        assert index.fields.filter == (
            "failure_category",
            "component",
            "root_cause_category",
            "contributing_factor_category",
            "architecture_category",
        )
        assert index.fields.embed == ("root_cause",)
        assert index.target.dsn_env == "DOSSIER_INDEX_DSN"

    def test_fields_over_two_outputs_are_refused_as_eval_refuses_them(self, tmp_path: Path):
        """Row 6 — the one where `extract` and `verify` both declare an output."""
        write_pipeline(tmp_path, steps=["extract", "verify"])

        said = refusal(tmp_path, declaration(fields="fields:\n  filter: [severity]\n"))

        assert said == (
            "incidents.yaml: fields are carried from one output, and 2 steps of "
            "incident-audit declare an output, as eval refuses it"
        )
