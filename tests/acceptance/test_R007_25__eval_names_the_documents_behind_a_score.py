"""R7.25 — `dossier eval` names the document behind every verdict it scored
incorrect, with the detail that says why.

R7.2 gives each field a percentage, which says where the work is. This says what
the work is. The distinction it turns on is R7.4 row 2's: a field at 0.0% because
nothing it cited could be located is a different problem from one at 0.0% because
the model read the wrong figure, and the percentage cannot tell them apart.

Built on the scoring example, so the numbers under test are the ones R7.2's own
table states, and the details are the ones scoring already composed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import (
    ANSWERS,
    FIELDS,
    ISSUES,
    PIPELINE,
    SOURCE_ID,
    SOURCE_TYPE,
    IssueTracker,
    RoutedModel,
)


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _lines_under(output: str, field: str) -> list[str]:
    """The indented lines following `field`'s own line, up to the next field."""
    lines = output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.split()[:1] == [field]]
    if not starts:
        return []
    collected = []
    for line in lines[starts[0] + 1 :]:
        if line.split()[:1] and line.split()[0] in FIELDS:
            break
        collected.append(line)
    return [line for line in collected if line.strip()]


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """The scoring example, synced and run, with its gold set in place."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    write_pipeline(workspace, sources=[SOURCE_ID])
    register_connector(
        monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker(ISSUES)
    )
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(ANSWERS))

    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    return workspace


class TestEvalNamesTheDocumentsBehindAScore:
    """R7.25 — the reason under the percentage it explains."""

    def test_a_field_below_full_marks_names_each_miss(self, audited, monkeypatch):
        """Row 1 — one line per incorrect verdict, under its field."""
        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")
        assert result.exit_code == 0, result.output

        under = _lines_under(result.output, "resolution_date")

        assert under, "resolution_date is at 75.0% and named no document"
        assert any("INC-" in line for line in under)

    def test_the_detail_distinguishes_ungrounded_from_a_mismatch(self, audited, monkeypatch):
        """Row 3 — R7.4 row 2's distinction, reaching a person."""
        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        details = " ".join(
            line for field in FIELDS for line in _lines_under(result.output, field)
        )

        assert "does not match" in details or "ungrounded" in details, details

    def test_a_field_at_full_marks_has_its_line_alone(self, audited, monkeypatch):
        """Row 4 — a correct verdict has no detail worth a line."""
        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        assert "100.0%" in result.output
        full = [
            field
            for field in FIELDS
            if any(
                line.split()[:1] == [field] and "100.0%" in line
                for line in result.output.splitlines()
            )
        ]
        assert full, result.output
        for field in full:
            assert _lines_under(result.output, field) == []

    def test_two_evals_of_one_run_read_identically(self, audited, monkeypatch):
        """Row 5 — the order is the run's, so the report is reproducible (R0.4)."""
        first = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")
        second = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        assert first.output == second.output

    def test_a_withheld_field_names_its_reason_and_no_documents(self, audited, monkeypatch):
        """Row 6 — nothing was scored, so there is nothing to explain (R7.15).

        `root_cause` is judged and this workspace has calibrated no judge, so it
        is withheld. A list of misses under it would be the number R7.5 just
        refused, arriving by the back door.
        """
        result = _cli(audited, monkeypatch, "eval", PIPELINE, "--gold", "gold/incidents")

        line = next(
            line for line in result.output.splitlines() if line.split()[:1] == ["root_cause"]
        )
        assert "--" in line, line
        assert _lines_under(result.output, "root_cause") == []
