"""R7.22 — `dossier calibrate` writes one calibration per grounding state.

Two judges, two samples, two files. A judge shown pages and a judge shown text
are asked two different questions, so a figure filed under the wrong one would
put a number behind a gate it was never measured for -- R7.15's failure with
better paperwork.

Through the CLI, because the thing being proved is what the command leaves on
disk beside the gold set, and because the path from `sources.yaml` to a rendered
page crosses the ledger, the converters and the cache.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

from dossier.application.eval import CALIBRATIONS_DIR, SHOWN_AS_PAGES
from dossier.domain.grounding import DESCRIBED
from dossier.domain.judges import MINIMUM_SAMPLE

PIPELINE = "incident-audit"
GOLD = "gold/incidents"
JUDGED = "root_cause"

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
# A PDF, because this is the only shape where both states are measurable at
# once: it converts to text *and* to pages, so one document can carry a
# grounded sample and a described one. A picture-only source cannot -- it has
# no text, so there are no grounded verdicts about it to measure.
DOCUMENT = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGES = 3

pytest.importorskip("pypdfium2", reason="the picture converters need the pdf extra")

SUPPORTED = json.dumps({"supported": True, "evidence": "stated on the page"})


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _use(monkeypatch, client) -> None:
    import dossier.cli.bootstrap as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


def _sample(path: Path, count: int = MINIMUM_SAMPLE) -> None:
    """A human-scored sample of `count` cases about the document (R7.16)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"c-{index:02d}",
                    "document": DOCUMENT,
                    "answer": f"candidate {index}",
                    "supported": index % 2 == 0,
                    "verified_by": "a.aleks",
                    "verified_at": "2026-09-19",
                }
            )
            for index in range(count)
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def calibratable(workspace: Path, monkeypatch):
    """A `per_part` workspace holding the postmortem, with samples for both states."""

    def build(*, described: int | None = MINIMUM_SAMPLE, mode: str = "per_part") -> Path:
        inbox = workspace / "inbox" / "postmortems"
        inbox.mkdir(parents=True, exist_ok=True)
        shutil.copy(CORPUS / DOCUMENT, inbox / DOCUMENT)

        (workspace / "sources.yaml").write_text(
            "sources:\n"
            "  - id: postmortems\n"
            "    type: folder\n"
            "    path: inbox/postmortems/\n"
            "    convert: [markdown, page_images]\n",
            encoding="utf-8",
        )
        inputs = {"extract": "documents@page_images"} if mode == "per_part" else {}
        write_pipeline(
            workspace,
            steps=["extract"],
            inputs=inputs,
            outputs={"extract": "schemas/incident.yaml"},
            sources=["postmortems"],
            modes={"extract": mode},
        )

        gold = workspace / GOLD
        (gold / "samples").mkdir(parents=True, exist_ok=True)
        _sample(gold / "samples" / f"{JUDGED}.jsonl")
        if described is not None:
            _sample(gold / "samples" / f"{JUDGED}.{DESCRIBED}.jsonl", described)

        assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
        assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
        return workspace

    return build


class TestCalibrateWritesOneCalibrationPerState:
    """R7.22 — the two judges are measured apart and kept apart."""

    def test_two_states_leave_two_files(self, calibratable, monkeypatch):
        """Example 1: the one where both judges are measured.

        The grounded name is unchanged, so a gold set written before there were
        two states is still read by the path it always was (R7.20 row 2).
        """
        from tests.fakes import FakeModelClient

        space = calibratable()
        _use(monkeypatch, FakeModelClient(responses=[SUPPORTED] * (2 * MINIMUM_SAMPLE)))

        result = _cli(space, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        written = sorted(p.name for p in (space / GOLD / CALIBRATIONS_DIR).iterdir())
        assert written == [f"{JUDGED}.{DESCRIBED}.json", f"{JUDGED}.json"]

    def test_the_described_judge_is_shown_pages(self, calibratable, monkeypatch):
        """Example 2: the one that makes the figure transferable.

        Half the calls carry a picture and the body `dossier eval` asks with;
        the other half carry the text and no parts. A state measured on a
        prompt it is not asked with is a figure about nothing.
        """
        from tests.fakes import FakeModelClient

        space = calibratable()
        judge = FakeModelClient(responses=[SUPPORTED] * (2 * MINIMUM_SAMPLE))
        _use(monkeypatch, judge)

        assert _cli(space, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD).exit_code == 0

        with_pages = [call for call in judge.calls if call["parts"]]
        assert len(with_pages) == MINIMUM_SAMPLE
        assert all(SHOWN_AS_PAGES in str(call["prompt"]) for call in with_pages)
        # Every page, not one. A `per_part` *stage* is shown a single page
        # because it answers about that page (R3.12); a judge is asked whether
        # the *document* supports a candidate, so it is shown the document
        # (R7.21). Showing it one page would make half the sample unanswerable
        # and the figure meaningless.
        assert all(len(call["parts"]) == PAGES for call in with_pages)

    def test_a_short_described_sample_is_refused_before_any_call(
        self, calibratable, monkeypatch
    ):
        """Example 3: nineteen cases buy nothing, and cost nothing.

        Refused before a judge is asked, naming the state -- otherwise the
        reader grows the wrong file (R7.14 row 3).
        """
        from tests.fakes import FakeModelClient

        space = calibratable(described=MINIMUM_SAMPLE - 1)
        judge = FakeModelClient(responses=[])
        _use(monkeypatch, judge)

        result = _cli(space, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 2
        assert DESCRIBED in result.output, result.output
        assert judge.call_count == 0
        assert not (space / GOLD / CALIBRATIONS_DIR).exists()

    def test_a_missing_described_sample_is_named_with_its_path(self, calibratable, monkeypatch):
        """Example 4: the one where the file to write is the answer.

        A `per_part` pipeline can produce a described verdict, so a sample for
        one is required -- and naming the path is what makes that actionable.
        """
        from tests.fakes import FakeModelClient

        space = calibratable(described=None)
        _use(monkeypatch, FakeModelClient(responses=[]))

        result = _cli(space, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 2
        assert f"{JUDGED}.{DESCRIBED}.jsonl" in result.output, result.output

    def test_a_per_file_pipeline_is_asked_for_one_sample(self, calibratable, monkeypatch):
        """Counter-example 5: the one where no described sample is looked for.

        Nothing here can produce a described verdict, so a sample for one would
        be twenty cases nobody can act on -- and its absence is not an error.
        """
        from tests.fakes import FakeModelClient

        space = calibratable(described=None, mode="per_file")
        _use(monkeypatch, FakeModelClient(responses=[SUPPORTED] * MINIMUM_SAMPLE))

        result = _cli(space, monkeypatch, "calibrate", PIPELINE, "--gold", GOLD)

        assert result.exit_code == 0, result.output
        written = sorted(p.name for p in (space / GOLD / CALIBRATIONS_DIR).iterdir())
        assert written == [f"{JUDGED}.json"]
