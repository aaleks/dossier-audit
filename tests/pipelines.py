"""Building a valid `pipeline.yaml` on disk, for tests that need one.

Not a fixture: several test files want a pipeline shaped slightly differently,
and a helper they call is easier to read at the call site than four fixtures
whose names have to encode their differences.
"""

from __future__ import annotations

import json
from pathlib import Path

# One tag per declared input, which is what R3.6 requires of a real prompt: every
# `{{...}}` is a declared input and every declared input appears. Generated per
# step rather than shared, because a single prompt naming only `{{documents}}` is
# invalid for any step declaring anything else.
TAGS = {"documents": "source_document", "reference": "procedure"}


def prompt_for(inputs: list[str]) -> str:
    """A prompt whose placeholders are exactly `inputs`, in declaration order."""
    lines = ["Extract the requested fields from the inputs below.", ""]
    for name in inputs:
        tag = TAGS.get(name, name.replace("(", "_").replace(")", ""))
        lines.append(f"<{tag}>{{{{{name}}}}}</{tag}>")
    return "\n".join(lines) + "\n"


def declared_names(declared: str) -> list[str]:
    """The input names in a `input:` value, whether written as a scalar or a list."""
    return [
        name.strip()
        for name in declared.strip().lstrip("[").rstrip("]").split(",")
        if name.strip()
    ]

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"document": {"type": "string"}},
}


def write_pipeline(
    root: Path,
    *,
    name: str = "incident-audit",
    steps: list[str] | None = None,
    inputs: dict[str, str] | None = None,
    outputs: dict[str, str | None] | None = None,
    sources: list[str] | None = None,
    reference: list[str] | None = None,
    model: str = "anthropic:claude-sonnet-4-5-20250929",
    write_schema: bool = True,
    schema_text: str | None = None,
) -> Path:
    """Write `pipelines/<name>/pipeline.yaml` and return its path."""
    steps = ["extract"] if steps is None else steps
    inputs = inputs or {}
    outputs = outputs or {}

    directory = root / "pipelines" / name
    (directory / "prompts").mkdir(parents=True, exist_ok=True)
    (directory / "schemas").mkdir(parents=True, exist_ok=True)

    if write_schema:
        (directory / "schemas" / "incident.json").write_text(
            schema_text if schema_text is not None else json.dumps(SCHEMA),
            encoding="utf-8",
        )

    lines = [
        f"sources: {sources if sources is not None else ['incidents-manual']}",
        f"model: {model}",
    ]
    if reference is not None:
        lines.append(f"reference: {reference}")
    lines.append("steps:")
    for step in steps:
        declared = inputs.get(step, "documents")
        (directory / "prompts" / f"{step}.md").write_text(
            prompt_for(declared_names(declared)), encoding="utf-8"
        )
        lines.append(f"  - id: {step}")
        lines.append(f"    prompt: prompts/{step}.md")
        lines.append(f"    input: {declared}")
        lines.append("    mode: per_file")
        output = outputs.get(step, "schemas/incident.json")
        if output is not None:
            lines.append(f"    output: {output}")

    path = directory / "pipeline.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
