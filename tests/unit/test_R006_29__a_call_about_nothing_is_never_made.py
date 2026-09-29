"""R6.29 — a call whose every input is empty is neither made nor served from
cache, and its document fails at that step, naming them.

Four rules closed one shape each of the same defect -- a model asked about an
input that came out empty (R6.13, R6.21, R3.16, R3.19). This one is at the call,
where the next shape will arrive. A call's inputs are what it is about: its
documents in each kind, and each earlier step's answer. A page counts; the
`reference` documents do not; empty is the empty string.

Run through `execute` and `replay`, with a model that keeps what each call was
shown, so the calls are **counted**. The empty document is `_fixtures.md`'s
`handover-note.md`, zero bytes, beside `INC-4821.md` in `incidents-manual`.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from tests.pipelines import prompt_for

from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.run import RunInputs, RunReport, execute, replay
from dossier.domain.conversion import PART_TYPE
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.ports import ImagePart

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
RUN_ID = "20260929T150000Z-0b0b"
INCIDENT = "INC-4821.md"
EMPTY = "handover-note.md"
MANUAL = {INCIDENT: "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n", EMPTY: ""}
EMPTIED = "every input it reads is empty: documents"
SCAN = "PLAY-2002-photocopy-no-text-layer.pdf"
# What `pdf-markdown` makes of it: its page anchor, and no text (spec 008).
ANCHORS = "<!-- page 1 -->"
PAGE = ("page-001.png", ImagePart(media_type=PART_TYPE, data=b"PLAY-2002 page 1"))
SHOWN = re.compile(r'<document key="([^"]+)">')


class Model:
    """A record for a structured call, the empty string for a prose one; keeps each call."""

    model_id = MODEL

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, schema=None, parts=()) -> str:
        shown = SHOWN.findall(prompt)
        self.calls.append({"shown": shown, "structured": schema is not None, "parts": parts})
        if schema is None:
            return ""
        return json.dumps({"document": shown[0] if shown else SCAN, "fields": []})


def _execute(
    workspace: Path,
    model: Model,
    *,
    steps: list[StepConfig] | None = None,
    text: dict[str, str] = MANUAL,
    parts: dict | None = None,
    run_id: str = RUN_ID,
) -> RunReport:
    """`extract` per_file over `text` unless `steps` says otherwise."""
    from dossier.infrastructure.cache import ArtifactCache

    steps = steps or [
        StepConfig(
            id="extract",
            prompt="prompts/extract.md",
            input="documents",
            mode="per_file",
            output="schemas/incident.yaml",
        )
    ]
    return execute(
        RunInputs(
            pipeline=PipelineConfig(
                name="incident-audit", sources=["incidents-manual"], model=MODEL, steps=steps
            ),
            pipeline_hash="0e52dd18" * 8,
            schemas={step.id: SCHEMA if step.output else None for step in steps},
            prompts={step.id: prompt_for([step.input]) for step in steps},
            documents={key: sha256(key.encode()).hexdigest() for key in text},
            document_text=text,
            document_content={"markdown": text},
            document_parts=parts,
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=run_id,
        started_at=datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
        dossier_version="0.1.0",
    )


def _result(report: RunReport, step: str, document: str):
    (done,) = [done for done in report.steps if done.step == step]
    (result,) = [result for result in done.results if result.document == document]
    return result


def _cached_about(workspace: Path, document: str) -> list[Path]:
    """The stage cache's files that mention `document`: its records name every input."""
    cache = workspace / ".dossier" / "cache" / "stage"
    return [
        path
        for path in cache.rglob("*")
        if path.is_file() and document in path.read_text(encoding="utf-8", errors="replace")
    ]


class TestACallAboutNothingIsNeverMade:
    """R6.29 — a call whose every input is empty fails its document, and is never made."""

    def test_an_empty_note_fails_and_is_never_asked(self, tmp_path: Path):
        """Row 1 — the one with an empty file beside a real incident."""
        model = Model()

        report = _execute(tmp_path, model)

        assert [call["shown"] for call in model.calls] == [[INCIDENT]]
        assert _result(report, "extract", EMPTY).error == EMPTIED
        assert not _result(report, "extract", INCIDENT).failed
        assert not (tmp_path / "runs" / RUN_ID / "extract" / f"{EMPTY}.json").exists()
        assert _cached_about(tmp_path, EMPTY) == []

    def test_an_earlier_step_that_answered_nothing_is_not_read(self, tmp_path: Path):
        """Row 2 — the one where `notes` answered INC-4821 with the empty string."""
        model = Model()
        steps = [
            StepConfig(
                id="notes", prompt="prompts/notes.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="verify",
                prompt="prompts/verify.md",
                input="notes",
                mode="per_file",
                output="schemas/incident.yaml",
            ),
        ]

        report = _execute(tmp_path, model, steps=steps, text={INCIDENT: MANUAL[INCIDENT]})

        assert [call["structured"] for call in model.calls] == [False], "verify was asked"
        assert _result(report, "verify", INCIDENT).error == (
            "every input it reads is empty: notes"
        )

    def test_an_answer_cached_about_nothing_is_not_served(self, tmp_path: Path, monkeypatch):
        """Row 3 — the one cached before this rule, under the note's key."""
        with monkeypatch.context() as before:
            # What every run did before R6.29: no call was ever about nothing.
            before.setattr("dossier.application.run.empty_inputs", lambda *a, **k: ())
            _execute(tmp_path, Model(), run_id="20260929T140000Z-0a0a")
        assert _cached_about(tmp_path, EMPTY) != [], "the old answer about nothing was cached"
        model = Model()

        report = _execute(tmp_path, model)

        assert model.calls == []
        assert _result(report, "extract", EMPTY).error == EMPTIED

    def test_a_run_with_a_note_that_failed_replays(self, tmp_path: Path):
        """Row 4 — the one reproduced without asking for what was never written (R4.7)."""
        from dossier.infrastructure.cache import ArtifactCache

        _execute(tmp_path, Model())

        replayed = replay(
            manifest=Manifest.read(tmp_path / "runs" / RUN_ID / MANIFEST_NAME),
            document_text=MANUAL,
            cache=ArtifactCache(tmp_path, namespace="stage"),
        )

        assert not _result(replayed, "extract", INCIDENT).failed
        assert _result(replayed, "extract", EMPTY).error == EMPTIED

    def test_a_page_is_something_to_ask_about(self, tmp_path: Path):
        """Row 5, counter-example — the one read as pictures, whose placeholder is empty."""
        model = Model()
        steps = [
            StepConfig(
                id="describe",
                prompt="prompts/describe.md",
                input="documents@page_images",
                mode="per_part",
                output="schemas/incident.yaml",
            )
        ]

        report = _execute(
            tmp_path,
            model,
            steps=steps,
            text={SCAN: ANCHORS},
            parts={"page_images": {SCAN: [PAGE]}},
        )

        assert [call["parts"] for call in model.calls] == [(PAGE[1],)]
        assert not _result(report, "describe", SCAN).failed

    def test_a_scan_with_only_its_anchors_is_asked(self, tmp_path: Path):
        """Row 6, counter-example — the one whose emptiness is the finding (spec 008)."""
        model = Model()

        report = _execute(tmp_path, model, text={SCAN: ANCHORS})

        assert [call["shown"] for call in model.calls] == [[SCAN]]
        assert not _result(report, "extract", SCAN).failed
