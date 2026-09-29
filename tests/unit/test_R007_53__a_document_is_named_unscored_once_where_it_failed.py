"""R7.53 — `dossier eval` names a document as not scored only when the scored
step has no answer for it, once, at the first step that failed it.

R7.52 named the failures of every step the replay reproduced. So a document a
step *after* the scored one failed was named as not scored though it was, and
a document two steps failed was named, and counted, twice. Found by `/verify`
on 2026-09-29.

Rows 1, 2, 3 and 5 are the decision itself, `unscored`, handed the failures in
pipeline order and the documents the scored step answered. Row 4 is the
`/verify` probe through the CLI: what a person running `dossier eval` read.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.acceptance.test_R007_54__compare_scores_both_runs_over_the_same_documents import (
    AFTER,
    Model,
    _run,
    _workspace,
)
from tests.fakes import NoModelClient

from dossier.domain.scoring import unscored

EMPTY = "every input it reads is empty: documents"
INVALID = "no valid output after 2 attempts: Invalid JSON: expected ident at line 1 column 2"
INCIDENTS = ("INC-4821", "INC-4822", "INC-4901", "INC-5455")


class TestADocumentIsNamedUnscoredOnceWhereItFailed:
    """R7.53 — named only when the scored step has no answer, once, at its first failure."""

    def test_a_document_the_scored_step_failed_is_named_there(self):
        """Row 1 — the one where the scored step failed it."""
        named = unscored(
            [("extract", "INC-4822", INVALID)],
            steps=["extract"],
            scored="extract",
            answered={"INC-4821", "INC-4901", "INC-5455"},
        )

        assert named == [("extract", "INC-4822", INVALID)]

    def test_a_document_two_steps_failed_is_named_once_at_the_first(self):
        """Row 2 — the one failed by both `notes` and `extract`, each reading `documents`."""
        named = unscored(
            [("notes", "handover-note.md", EMPTY), ("extract", "handover-note.md", EMPTY)],
            steps=["notes", "extract"],
            scored="extract",
            answered={"INC-4821.md"},
        )

        assert named == [("notes", "handover-note.md", EMPTY)]

    def test_a_document_skipped_for_an_earlier_failure_is_named_at_it(self):
        """Row 3 — the one `extract` skipped, because `notes`, which it reads, failed it."""
        named = unscored(
            [("notes", "handover-note.md", EMPTY)],
            steps=["notes", "extract"],
            scored="extract",
            answered={"INC-4821.md"},
        )

        assert named == [("notes", "handover-note.md", EMPTY)]

    def test_a_failure_after_the_scored_step_is_not_named(self, workspace: Path, monkeypatch):
        """Row 4, counter-example — the one `verify`, after `extract`, failed.

        Through the CLI, as `/verify` found it: `4 documents · … · 1 failed`,
        then `not scored: INC-4821 failed at verify`, of a document it scored.
        """
        import dossier.cli.bootstrap as cli

        _workspace(workspace, monkeypatch, **AFTER)
        _run(workspace, monkeypatch, Model(silent="INC-4821"))
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())

        result = _cli(
            workspace, monkeypatch, "eval", "incident-audit", "--gold", "gold/incidents"
        )

        assert result.exit_code == 0, result.output
        headline = next(line for line in result.output.splitlines() if " fields · " in line)
        assert re.fullmatch(r"4 documents · \d+ fields · overall \d+\.\d%", headline), headline
        assert "not scored" not in result.output, result.output

    def test_a_failure_before_the_scored_step_it_does_not_read_is_not_named(self):
        """Row 5, counter-example — the one `extract` answered, though `verify` failed it."""
        named = unscored(
            [("verify", "INC-4821", "every input it reads is empty: notes")],
            steps=["notes", "verify", "extract"],
            scored="extract",
            answered=set(INCIDENTS),
        )

        assert named == []
