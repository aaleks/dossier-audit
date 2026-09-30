"""R17.5 — `dossier status` changes no file.

A command whose job is to look must not move what it looks at. The ledger is
where it could: `Ledger` creates the file, and migrates an older one, as it
opens it. So the claim is checked on every file in the workspace, byte for
byte, rather than on the ones `status` is expected to read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.test_R007_14__calibrate_writes_the_calibration_file import (
    _cases,
    _replies,
)
from tests.acceptance.test_R017_7__status_says_what_eval_will_withhold import (
    GOLD,
    _cli,
    audited_workspace,
)
from tests.fakes import FakeModelClient, NoModelClient, register_connector
from tests.scoring_example import PIPELINE, SOURCE_TYPE, IssueTracker


@pytest.fixture
def audited(workspace: Path, monkeypatch) -> Path:
    """R17.7's workspace: synced and run, a bar and a sample beside the gold set."""
    return audited_workspace(workspace, monkeypatch)


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestStatusChangesNoFile:
    """R17.5 — every file holds the bytes it held, and none is added."""

    def test_status_over_a_synced_run_and_calibrated_workspace_changes_nothing(
        self, audited: Path, monkeypatch
    ):
        """Row 1 — the one with a ledger, a run and a calibration to read."""
        import dossier.cli.bootstrap as cli

        judge = FakeModelClient(responses=_replies(_cases()))
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: judge)
        assert _cli(audited, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD).exit_code == 0
        monkeypatch.setattr(cli, "build_model_client", lambda model_id: NoModelClient())
        before = _files(audited)

        result = _cli(audited, monkeypatch, "status", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        assert _files(audited) == before

    def test_a_workspace_never_synced_is_given_no_ledger(self, tmp_path: Path, monkeypatch):
        """Row 2, counter-example — the one with no `.dossier/` at all.

        Opened the way `sync` opens it, the ledger would be created to be read.
        """
        (tmp_path / "sources.yaml").write_text(
            f"sources:\n  - id: procedures-confluence\n    type: {SOURCE_TYPE}\n",
            encoding="utf-8",
        )
        register_connector(
            monkeypatch, SOURCE_TYPE, lambda config, *, workspace: IssueTracker({})
        )

        result = _cli(tmp_path, monkeypatch, "status")

        assert result.exit_code == 0, result.output
        assert "  procedures-confluence · never synced" in result.output.splitlines()
        assert not (tmp_path / ".dossier").exists()
