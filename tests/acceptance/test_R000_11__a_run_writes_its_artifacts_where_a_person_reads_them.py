"""R0.11 — a completed `dossier run` writes each artifact a step produced or served
to `runs/<run_id>/<step>/<document>.json`, the same bytes the cache holds.

The cache under `.dossier/` is where an artifact is kept; the run directory is
where a person reads it. Every other spec already names the second path, and
this is the rule that makes it exist.

These rows go through the CLI, because "where a person reads it" is a claim
about the workspace a command leaves behind, and the path from a model's answer
to a file under `runs/` crosses the stage loop, the cache and the run directory.
The bytes are compared against the cache entry rather than against a canned
string, so the test cannot pass by writing *something* under the right name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.pipelines import write_pipeline

pytestmark = pytest.mark.outer_loop

PIPELINE = "incident-audit"
# The folder source's keys are file names, so the artifact for `INC-4821.md`
# is `INC-4821.md.json`: the key with `.json` appended, never a suffix replaced.
DOCUMENTS = ("INC-4821.md", "INC-4822.md", "audit-note.md")


def _cli(workspace: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from dossier.cli.main import app

    monkeypatch.chdir(workspace)
    return CliRunner().invoke(app, list(args))


def _answer(document: str) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "summary",
                    "value": "reviewed",
                    "source": {"document": document, "span": "Reopened"},
                }
            ],
        }
    )


def _use(monkeypatch, client) -> None:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: client, raising=False)


def _cached(workspace: Path) -> dict[tuple[str, str], tuple[bytes, bytes]]:
    """Every stage cache entry, keyed by (step, document): (artifact, record).

    The record names the document it was computed for, so a run directory can
    be checked against the cache without knowing how a key is composed.
    """
    root = workspace / ".dossier" / "cache" / "stage"
    entries = {}
    for record in sorted(root.rglob("*.meta.json")):
        meta = json.loads(record.read_text(encoding="utf-8"))
        document = meta["inputs"][0]["path"].split("/", 1)[1]
        artifact = record.with_name(record.name.removesuffix(".meta.json"))
        entries[(meta["step"], document)] = (artifact.read_bytes(), record.read_bytes())
    return entries


def _run_dirs(workspace: Path) -> list[Path]:
    runs = workspace / "runs"
    return sorted(runs.iterdir()) if runs.is_dir() else []


@pytest.fixture
def synced(workspace: Path, monkeypatch) -> Path:
    write_pipeline(workspace, steps=["extract"])
    assert _cli(workspace, monkeypatch, "sync", PIPELINE).exit_code == 0
    assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
    return workspace


@pytest.fixture
def completed(synced: Path, monkeypatch) -> Path:
    """One finished run, and its directory under `runs/`."""
    from tests.fakes import FakeModelClient

    _use(monkeypatch, FakeModelClient(responses=[_answer(key) for key in DOCUMENTS]))
    result = _cli(synced, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return _run_dirs(synced)[-1]


class TestARunWritesItsArtifactsWhereAPersonReadsThem:
    """R0.11 — the run directory holds what the cache holds, by name."""

    def test_the_artifact_a_person_opens_is_the_cache_entry_by_name(
        self, synced: Path, completed: Path
    ):
        """Example 1: the one where `extract/INC-4821.md.json` is the cache entry.

        Byte-identical, with the provenance record beside it (R0.3), and for
        every document the run covered, not just one.
        """
        cached = _cached(synced)
        assert len(cached) == len(DOCUMENTS)

        for document in DOCUMENTS:
            artifact, record = cached[("extract", document)]
            written = completed / "extract" / f"{document}.json"
            assert written.is_file(), f"{written.relative_to(synced)} was not written"
            assert written.read_bytes() == artifact
            assert written.with_name(f"{document}.meta.json").read_bytes() == record

    def test_a_cache_hit_is_still_an_output(self, synced: Path, monkeypatch, completed: Path):
        """Example 2: the one where the second run costs no calls and is still written out.

        `NoModelClient` fails at the call site, so a single call would be an
        error here, not a miscount. The second directory holds the same bytes
        as the first (R5.5).
        """
        from tests.fakes import NoModelClient

        _use(monkeypatch, NoModelClient())

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        first, second = _run_dirs(synced)
        assert first == completed
        for document in DOCUMENTS:
            name = f"extract/{document}.json"
            assert (second / name).read_bytes() == (first / name).read_bytes()

    def test_a_run_that_dies_in_verify_leaves_extract_complete(self, synced: Path, monkeypatch):
        """Example 3: the one where the process is killed while `verify` is running.

        The client is scripted for `extract` only, so the first `verify` call
        raises out of the run. Each file is written as its document completes,
        so `extract/` is complete under the run directory when that happens
        (R4.1 row 4).
        """
        from tests.fakes import FakeModelClient

        write_pipeline(synced, steps=["extract", "verify"], inputs={"verify": "previous"})
        _use(monkeypatch, FakeModelClient(responses=[_answer(key) for key in DOCUMENTS]))

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code != 0
        run = _run_dirs(synced)[-1]
        expected = sorted(
            name
            for document in DOCUMENTS
            for name in (f"{document}.json", f"{document}.meta.json")
        )
        assert sorted(path.name for path in (run / "extract").iterdir()) == expected
        assert not (run / "verify").exists() or not any((run / "verify").iterdir())

    def test_a_failed_document_has_nothing_standing_in_for_it(self, synced: Path, monkeypatch):
        """Example 4: the one where `INC-4821` fails validation twice (R6.9).

        Two answers that are not JSON, then valid ones for the other two. The
        failure is on stdout and in the exit code; under `runs/` there is no
        artifact and no record for it, and the other two are present.
        """
        from tests.fakes import FakeModelClient

        responses = ["not json", "still not json", *(_answer(key) for key in DOCUMENTS[1:])]
        _use(monkeypatch, FakeModelClient(responses=responses))

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 1, result.output
        run = _run_dirs(synced)[-1]
        assert not (run / "extract" / "INC-4821.md.json").exists()
        assert not (run / "extract" / "INC-4821.md.meta.json").exists()
        for document in DOCUMENTS[1:]:
            assert (run / "extract" / f"{document}.json").is_file()

    def test_a_text_step_writes_markdown(self, synced: Path, monkeypatch):
        """Example 5: the one where `report` declares no output.

        A step with no `output` returns text rather than a field record, and its
        file carries `.md`: the text the model returned, byte for byte.
        """
        from tests.fakes import FakeModelClient

        write_pipeline(synced, steps=["report"], outputs={"report": None})
        texts = {key: f"# Report on {key}\n\nNothing to add.\n" for key in DOCUMENTS}
        _use(monkeypatch, FakeModelClient(responses=list(texts.values())))

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        run = _run_dirs(synced)[-1]
        for document, text in texts.items():
            written = run / "report" / f"{document}.md"
            assert written.is_file(), f"{written.relative_to(synced)} was not written"
            assert written.read_text(encoding="utf-8") == text
            assert not (run / "report" / f"{document}.json").exists()

    def test_the_run_directory_is_never_read_back(
        self, synced: Path, monkeypatch, completed: Path
    ):
        """Counter-example (row 6): the one where a reviewer deletes a file under `runs/`.

        The next run is a cache hit with zero model calls. `runs/` is a copy for
        a person; the cache is the only authority (R5.9), so nothing missing
        under `runs/` is missing to `dossier`.
        """
        from tests.fakes import NoModelClient

        (completed / "extract" / "INC-4821.md.json").unlink()
        _use(monkeypatch, NoModelClient())

        result = _cli(synced, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "3 from cache" in result.output
        assert (_run_dirs(synced)[-1] / "extract" / "INC-4821.md.json").is_file()

    def test_planning_writes_no_run_directory(self, synced: Path, monkeypatch, completed: Path):
        """Counter-example (row 7): the one where `--plan` reports work and does none (R4.6)."""
        from tests.fakes import NoModelClient

        _use(monkeypatch, NoModelClient())
        before = _run_dirs(synced)

        result = _cli(synced, monkeypatch, "run", PIPELINE, "--plan")

        assert result.exit_code == 0, result.output
        assert _run_dirs(synced) == before
