"""R21.23 — `eval` compares a masked run's answer with its gold value masked by the
document's numbering.

A masked run quotes the masked text it was shown, so its answer reads
`[PERSON_2]'s settlement was held` where the document read `Erika
Mustermann's`. The gold value was written by a person against the document
and reads the name. Compared as written they never agree, and a run that
quoted exactly the right span would score wrong. So the gold value is masked
by the document's own mapping (R21.21, R21.22) before it is compared. The eval
asks no masker: the mapping is the run's, from the cache (R21.6).

`PLAY-6001` names `Hans Muster` first, so he is `[PERSON_1]` and `Erika
Mustermann` `[PERSON_2]`. `affected_systems` is the declaration's `reference`
field, compared as text (R7.1); `severity` its enum.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.fakes import FakeMasker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, IssueTracker, RoutedModel, abstains, found

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
GOLD = "gold/masked"
PLAY_6001 = (
    "# PLAY-6001\n\n"
    "Hans Muster opened the ticket.\n"
    "Erika Mustermann's settlement was held for two days.\n"
    "Severity was assessed as major.\n"
)
MASKING = "masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\nentities: [PERSON]\n"


def _answers(span: str) -> dict:
    return {
        "PLAY-6001": [
            found("PLAY-6001", "affected_systems", span, span),
            found("PLAY-6001", "severity", "major", "Severity was assessed as major"),
            *(abstains(f) for f in FIELDS if f not in ("affected_systems", "severity")),
        ]
    }


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _eval(workspace: Path, monkeypatch, *, gold_value: str, masked: bool = True) -> str:
    """Sync, run and eval `PLAY-6001`; the eval's output."""
    import dossier.cli.bootstrap as cli

    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE_ID}\n    type: {SOURCE_TYPE}\n", encoding="utf-8"
    )
    path = write_pipeline(workspace, name=PIPELINE, sources=[SOURCE_ID])
    if masked:
        with path.open("a", encoding="utf-8") as pipeline:
            pipeline.write("masking: masking/cid.yaml\n")
        (path.parent / "masking").mkdir()
        (path.parent / "masking" / "cid.yaml").write_text(MASKING, encoding="utf-8")
    gold = workspace / GOLD
    gold.mkdir(parents=True)
    (gold / "PLAY-6001.json").write_text(
        json.dumps(
            {
                "document": "PLAY-6001",
                "verified_by": "a.aleks",
                "verified_at": "2026-10-03",
                "fields": {
                    "affected_systems": {"value": gold_value},
                    "severity": {"value": "major"},
                },
            }
        ),
        encoding="utf-8",
    )
    register_connector(
        monkeypatch,
        SOURCE_TYPE,
        lambda config, *, workspace: IssueTracker({"PLAY-6001": PLAY_6001}),
    )
    span = (
        "[PERSON_2]'s settlement was held"
        if masked
        else "Erika Mustermann's settlement was held"
    )
    masker = FakeMasker()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: RoutedModel(_answers(span)))
    monkeypatch.setattr(cli, "build_masker", lambda declaration: masker, raising=False)
    for args in (("sync", PIPELINE), ("run", PIPELINE)):
        result = _cli(workspace, monkeypatch, *args)
        assert result.exit_code == 0, result.output
    asked = masker.call_count
    result = _cli(workspace, monkeypatch, "eval", PIPELINE, "--gold", GOLD)
    assert result.exit_code == 0, result.output
    assert masker.call_count == asked, "an eval asks no masker"
    return result.output


def _field(output: str, name: str) -> str:
    (line,) = [line for line in output.splitlines() if line.split()[:1] == [name]]
    return re.search(r"\d+\.\d%", line).group()


class TestEvalComparesMaskedAnswersWithMaskedGold:
    """R21.23 — gold masked by the document's mapping, then compared as R7.1 compares."""

    def test_a_masked_answer_matches_gold_that_names_the_same_client(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where gold names Erika Mustermann and the run quotes [PERSON_2]."""
        output = _eval(
            workspace, monkeypatch, gold_value="Erika Mustermann's settlement was held"
        )

        assert _field(output, "affected_systems") == "100.0%"

    def test_gold_naming_another_client_does_not_match(self, workspace: Path, monkeypatch):
        """Row 2: the one where gold names Hans Muster: `[PERSON_1]` is not `[PERSON_2]`."""
        output = _eval(workspace, monkeypatch, gold_value="Hans Muster's settlement was held")

        assert _field(output, "affected_systems") == "0.0%"

    def test_an_enum_is_compared_as_written(self, workspace: Path, monkeypatch):
        """Row 3: the one where an enum's value is never client data."""
        output = _eval(
            workspace, monkeypatch, gold_value="Erika Mustermann's settlement was held"
        )

        assert _field(output, "severity") == "100.0%"

    def test_an_unmasked_run_is_compared_with_gold_as_written(
        self, workspace: Path, monkeypatch
    ):
        """Row 4, a counter-example: the one where nothing is declared, as spec 007 compares."""
        output = _eval(
            workspace,
            monkeypatch,
            gold_value="Erika Mustermann's settlement was held",
            masked=False,
        )

        assert _field(output, "affected_systems") == "100.0%"
