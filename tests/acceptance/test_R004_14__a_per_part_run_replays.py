"""R4.14 — a replay reproduces a `per_part` step part by part.

R3.12 put each part in its own key and the replay was never taught about it, so
`_replay_one` recomposed a key with no part in it -- one no `per_part` run had
ever written. Every such run was irreproducible, which took `dossier eval` with
it, because eval scores a replay rather than the workspace.

Through the CLI, as R4.7's rows are, and for the same reason: the path from
`runs/<run_id>/manifest.json` back to reproduced artifacts crosses the manifest,
the snapshot store, the converters and two caches, and any one of them reading
today's configuration would break the rule with every unit test still green.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline


def _pages(directory: Path) -> list[Path]:
    """The artifacts, without the provenance record beside each one (R0.11)."""
    return sorted(p for p in directory.glob("*.json") if not p.name.endswith(".meta.json"))


PIPELINE = "incident-audit"

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
PDF = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = 3

pytest.importorskip("pypdfium2", reason="the per_part slice needs the 'pdf' extra")

SPAN = "total exposure CHF 48'200"


def _described(page: int) -> str:
    """One page's answer, citing a span no converted text holds (R6.15)."""
    return json.dumps(
        {
            "document": PDF,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00 + page,
                    "currency": "CHF",
                    "source": {"document": PDF, "span": SPAN, "page": page},
                }
            ],
        }
    )


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


@pytest.fixture
def ran(workspace: Path, monkeypatch) -> tuple[Path, str]:
    """A completed run of a `per_part` step, and the run id it wrote."""
    from tests.fakes import FakeModelClient

    inbox = workspace / "inbox" / "postmortems"
    inbox.mkdir(parents=True)
    shutil.copy(CORPUS / PDF, inbox / PDF)

    (workspace / "sources.yaml").write_text(
        "sources:\n"
        "  - id: postmortems\n"
        "    type: folder\n"
        "    path: inbox/postmortems/\n"
        "    convert: [page_images]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        steps=["extract"],
        inputs={"extract": "documents@page_images"},
        outputs={"extract": "schemas/incident.yaml"},
        sources=["postmortems"],
        modes={"extract": "per_part"},
    )

    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
    _use(monkeypatch, FakeModelClient(responses=[_described(n) for n in (1, 2, 3)]))
    assert _cli(workspace, monkeypatch, "run", PIPELINE).exit_code == 0

    completed = sorted(p.name for p in (workspace / "runs").iterdir() if p.is_dir())[-1]
    return workspace, completed


def _replay(workspace: Path, monkeypatch, completed: str):
    return _cli(workspace, monkeypatch, "run", PIPELINE, "--replay", f"runs/{completed}")


class TestAPerPartRunReplays:
    """R4.14 — the fan-out is reproduced, not flattened."""

    def test_every_page_is_reproduced(self, ran: tuple[Path, str], monkeypatch):
        """Example 1: the one that could not happen at all before.

        Three artifacts for a three-page document. The count is the assertion:
        a replay that reproduced the document once, or that stopped on the
        first page, is the two failures this rule sits between.
        """
        workspace, completed = ran

        result = _replay(workspace, monkeypatch, completed)

        assert result.exit_code == 0, result.output
        assert f"{PAGES} artifact(s) reproduced" in result.output, result.output
        assert "no model calls" in result.output

    def test_what_it_wrote_is_what_the_run_wrote(self, ran: tuple[Path, str], monkeypatch):
        """Example 2: byte-identical, under the replay's own directory (R0.12).

        Each page under its own name, and the run's own directory untouched --
        a replay that overwrote what it was checking would always agree with
        itself.
        """
        workspace, completed = ran
        original = _pages(workspace / "runs" / completed / "extract" / PDF)
        assert [p.name for p in original] == ["page-001.json", "page-002.json", "page-003.json"]
        before = [p.read_bytes() for p in original]

        assert _replay(workspace, monkeypatch, completed).exit_code == 0

        replays = next((workspace / "runs" / completed / "replays").iterdir())
        written = _pages(replays / "extract" / PDF)
        assert [p.name for p in written] == [p.name for p in original]
        assert [p.read_bytes() for p in written] == before
        assert [p.read_bytes() for p in original] == before, "the run's own output moved"

    def test_a_missing_part_stops_the_replay_and_writes_nothing(
        self, ran: tuple[Path, str], monkeypatch
    ):
        """Example 4: the one where half a document is not a document.

        A run directory holding two pages of three reads as a complete replay
        to anyone who did not see the error, which is why R0.12 writes nothing
        at all rather than what it managed.
        """
        workspace, completed = ran
        entries = sorted((workspace / ".dossier" / "cache" / "stage").rglob("*"))
        artifact = next(p for p in entries if p.is_file() and p.suffix not in {".json"})
        artifact.unlink()

        result = _replay(workspace, monkeypatch, completed)

        assert result.exit_code == 2, result.output
        assert "extract" in result.output
        assert not list((workspace / "runs" / completed / "replays").glob("*")), (
            "a failed replay left a directory behind"
        )
