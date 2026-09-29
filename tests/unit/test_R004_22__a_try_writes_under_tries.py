"""R4.22 — a try writes its answers under `tries/<try_id>/`, named as a run's
are, and prints what a run prints.

A try id has the form of a run id. Under it, each artifact is named as R0.11
names a run's, and as R0.13 names a `per_part` step's pages. The terminal shows
the step lines and every field finding as `dossier run` shows them (R6.16), so
reading a try is reading a run.

Rows 1 and 3 through the CLI, because the terminal is read there. The incidents
are markdown in a folder source, so their keys carry the extension
(`INC-4821.md`), as R3.17's do. Row 2 through `execute`, with `_fixtures.md`'s
"`INC-4830` page by page" as three pictures.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.fakes import FakeModelClient
from tests.pipelines import prompt_for, write_pipeline
from tests.scoring_example import FIELDS, abstains

from dossier.application.run import RunInputs, execute
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart

PIPELINE = "incident-audit"
INCIDENTS = {
    "INC-4821.md": "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n",
    "INC-4822.md": "# INC-4822\n\nThe payment gateway timed out for two hours.\n",
}
SHOWN = re.compile(r'<document key="([^"]+)">')
# The form of a run id (R0.11): a sortable timestamp and four hex characters.
AN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{4}")

TRY = "20260929T100000Z-1a2b"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = [
    (f"page-00{n}.png", ImagePart(media_type=PART_TYPE, data=f"INC-4830 page {n}".encode()))
    for n in (1, 2, 3)
]


class Model:
    """Answers every call with nothing extracted."""

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        (document,) = SHOWN.findall(prompt)
        return json.dumps({"document": document, "fields": [abstains(f) for f in FIELDS]})


def _dossier_run(workspace: Path, monkeypatch, *documents: str):
    """Sync the two incidents, then `dossier run`, with `--doc` for each of `documents`."""
    import dossier.cli.bootstrap as cli

    for name, text in INCIDENTS.items():
        path = workspace / "inbox" / "tickets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: tickets\n    type: folder\n    path: inbox/tickets/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=["tickets"])
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: Model())
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    named = [argument for document in documents for argument in ("--doc", document)]
    return _cli(workspace, monkeypatch, "run", PIPELINE, *named)


def _entries(path: Path) -> list[str]:
    return sorted(entry.name for entry in path.iterdir()) if path.is_dir() else []


class TestATryWritesUnderTries:
    """R4.22 — a try writes under `tries/<try_id>/`, named as a run's are."""

    def test_a_try_is_filed_and_printed_as_a_run_is(self, workspace: Path, monkeypatch):
        """Row 1 — the one where INC-4821's answer and its record are under the try's id."""
        result = _dossier_run(workspace, monkeypatch, "INC-4821.md")

        assert result.exit_code == 0, result.output
        (try_id,) = _entries(workspace / "tries")
        assert AN_ID.fullmatch(try_id), try_id
        assert _entries(workspace / "tries" / try_id / "extract") == [
            "INC-4821.md.json",
            "INC-4821.md.meta.json",
        ]
        lines = result.output.splitlines()
        assert lines[0] == f"try {try_id} · tries/{try_id}/", result.output
        assert lines[1].startswith("  extract: 1 document(s) · 0 from cache"), result.output

    def test_a_page_by_page_try_files_each_page(self, tmp_path: Path):
        """Row 2 — the one where INC-4830's three pages are three files, as a run's are."""
        from dossier.infrastructure.cache import ArtifactCache

        execute(
            RunInputs(
                pipeline=PipelineConfig(
                    name=PIPELINE,
                    sources=["postmortems"],
                    model=Model.model_id,
                    steps=[
                        StepConfig(
                            id="extract",
                            prompt="prompts/extract.md",
                            input="documents@page_images",
                            mode="per_part",
                        )
                    ],
                ),
                pipeline_hash="6e0d4b27" * 8,
                schemas={
                    "extract": OutputSchema(
                        schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                    )
                },
                prompts={"extract": prompt_for(["documents@page_images"])},
                documents={POSTMORTEM: sha256(POSTMORTEM.encode()).hexdigest()},
                document_text={POSTMORTEM: "SEV-1 | Checkout TLS expiry"},
                document_content={"markdown": {POSTMORTEM: "SEV-1 | Checkout TLS expiry"}},
                document_parts={"page_images": {POSTMORTEM: PAGES}},
            ),
            workspace=tmp_path,
            model=FakeModelClient(
                responses=[json.dumps({"document": POSTMORTEM, "fields": []})] * 3
            ),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id=TRY,
            started_at=datetime(2026, 9, 29, 10, 0, tzinfo=UTC),
            dossier_version="0.1.0",
            tried=(POSTMORTEM,),
        )

        answers = _entries(tmp_path / "tries" / TRY / "extract" / POSTMORTEM)
        assert [name for name in answers if not name.endswith(".meta.json")] == [
            "page-001.json",
            "page-002.json",
            "page-003.json",
        ]
        assert not (tmp_path / "runs").exists()

    def test_a_run_naming_no_document_is_filed_under_runs(self, workspace: Path, monkeypatch):
        """Row 3, counter-example — the one with no `--doc`: a run, and its manifest."""
        result = _dossier_run(workspace, monkeypatch)

        assert result.exit_code == 0, result.output
        (run_id,) = _entries(workspace / "runs")
        assert (workspace / "runs" / run_id / "manifest.json").is_file()
        assert result.output.splitlines()[0].startswith(f"run {run_id} · "), result.output
        assert not (workspace / "tries").exists()
