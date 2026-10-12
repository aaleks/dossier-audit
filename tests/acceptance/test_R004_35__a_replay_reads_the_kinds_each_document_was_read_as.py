"""R4.35 — a manifest pins the kinds each document was read as, and a replay
reads those and no others.

A replay decided which kinds a document held from the converters pinned for its
media type, which is a fact about a media type. `INC-4830`'s `page_images`
container gone from the cache read as a document that never had pages, and the
replay exited 0 with none of them; a second source mapping its PDFs to
`page_images` alone was asked for `markdown` it never made, and refused. Here
`INC-4830` is in `incidents-manual`, converted to `markdown` and `page_images`,
and `INC-4977` in `incidents-screenshots`, converted to `page_images` alone;
`extract` reads text, and `describe` reads pages one at a time.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

pytest.importorskip("pypdfium2", reason="page images need the 'pdf' extra")

PIPELINE = "incident-audit"
CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "postmortems" / "pdf"
MANUAL, SCREENSHOTS = "incidents-manual", "incidents-screenshots"
INC_4830 = "INC-4830-postmortem-checkout-tls-expiry.pdf"
INC_4977 = "INC-4977-postgres-wal-disk-full.pdf"
MAGIC = b"DOSSIER-PARTS 1\n"
STEPS = ("extract", "describe")


class Abstaining:
    """A model abstaining on every field, counting what it was asked.

    Every call answers, so every unit the run asks about writes an artifact, and
    a replay reproducing fewer than the run wrote has something to be short of.
    A page reaches it as a picture alone, so it is counted rather than named.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.calls.append("page" if parts else "text")
        return json.dumps({"document": INC_4830, "fields": [abstains(f) for f in FIELDS]})


def _sources(workspace: Path, screenshots: str) -> None:
    (workspace / "sources.yaml").write_text(
        "sources:\n"
        f"  - id: {MANUAL}\n    type: folder\n    path: inbox/manual/\n"
        "    convert: [markdown, page_images]\n"
        f"  - id: {SCREENSHOTS}\n    type: folder\n    path: inbox/screenshots/\n"
        f"    convert:{screenshots}\n",
        encoding="utf-8",
    )


PICTURES_ALONE = "\n      application/pdf: [page_images]"


def _workspace(workspace: Path, monkeypatch, *, layout: dict[str, str]) -> Abstaining:
    """The PDFs in their folders, synced and converted; the model, abstaining."""
    import dossier.cli.bootstrap as cli

    for folder, name in layout.items():
        inbox = workspace / "inbox" / folder
        inbox.mkdir(parents=True)
        shutil.copy(CORPUS / name, inbox / name)
    _sources(workspace, PICTURES_ALONE)
    write_pipeline(
        workspace,
        name=PIPELINE,
        steps=list(STEPS),
        inputs={"extract": "documents", "describe": "documents@page_images"},
        outputs={step: "schemas/incident.yaml" for step in STEPS},
        sources=[MANUAL, SCREENSHOTS],
        modes={"describe": "per_part"},
    )
    model = Abstaining()
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    for command in ("sync", "convert"):
        assert _cli(workspace, monkeypatch, command, PIPELINE).exit_code == 0
    return model


def _run(workspace: Path, monkeypatch) -> str:
    result = _cli(workspace, monkeypatch, "run", PIPELINE)
    assert result.exit_code == 0, result.output
    return sorted(p.name for p in (workspace / "runs").iterdir() if p.is_dir())[-1]


def _pinned(workspace: Path, run_id: str) -> dict[str, dict]:
    manifest = json.loads((workspace / "runs" / run_id / "manifest.json").read_text("utf-8"))
    return {document["key"]: document for document in manifest["plan"]["documents"]}


def _replay(workspace: Path, monkeypatch, run_id: str):
    return _cli(workspace, monkeypatch, "run", "--replay", f"runs/{run_id}/")


def _artifacts(root: Path) -> dict[str, bytes]:
    """Every artifact under the steps' directories, without its provenance record (R0.11)."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for step in STEPS
        for path in sorted((root / step).rglob("*"))
        if path.is_file() and not path.name.endswith(".meta.json")
    }


def _replayed(workspace: Path, run_id: str) -> Path:
    (written,) = (workspace / "runs" / run_id / "replays").iterdir()
    return written


def _container(workspace: Path, run_id: str, key: str) -> Path:
    """`key`'s `page_images` container in the cache, found by the key the run wrote it under."""
    from dossier.application.convert import convert_inputs
    from dossier.domain.keys import cache_key

    manifest = json.loads((workspace / "runs" / run_id / "manifest.json").read_text("utf-8"))
    (converter,) = [c for c in manifest["plan"]["converters"] if c["kind"] == "page_images"]
    entry = cache_key(
        convert_inputs(
            snapshot=_pinned(workspace, run_id)[key]["snapshot"],
            converter_id=converter["id"],
            converter_version=converter["version"],
        )
    )
    (found,) = (workspace / ".dossier" / "cache" / "convert").rglob(entry)
    assert found.read_bytes().startswith(MAGIC)
    return found


@pytest.fixture
def ran(workspace: Path, monkeypatch) -> tuple[Path, str, Abstaining]:
    """`INC-4830` and `INC-4977` run through both steps, and the run id."""
    model = _workspace(
        workspace, monkeypatch, layout={"manual": INC_4830, "screenshots": INC_4977}
    )
    return workspace, _run(workspace, monkeypatch), model


class TestAReplayReadsTheKindsEachDocumentWasReadAs:
    """R4.35 — what the run read each document as, pinned, and read back."""

    def test_the_manifest_pins_what_each_document_was_read_as(self, ran):
        """Rows 1 and 3 — `INC-4830` as text and pages, `INC-4977` as pages alone."""
        workspace, run_id, model = ran

        pinned = _pinned(workspace, run_id)

        assert pinned[INC_4830]["kinds"] == ["markdown", "page_images"]
        assert pinned[INC_4977]["kinds"] == ["page_images"]
        assert model.calls.count("text") == 1, model.calls

    def test_a_container_gone_stops_the_replay_by_name(self, ran, monkeypatch):
        """Row 2 — the one that exited 0 with none of `INC-4830`'s pages."""
        workspace, run_id, _ = ran
        _container(workspace, run_id, INC_4830).unlink()

        result = _replay(workspace, monkeypatch, run_id)

        assert result.exit_code == 2, result.output
        assert "'describe'" in result.stderr and INC_4830 in result.stderr, result.stderr
        assert not (workspace / "runs" / run_id / "replays").exists()

    def test_a_source_of_pictures_alone_replays(self, ran, monkeypatch):
        """Row 3 — the one refused for `markdown` the run never made of `INC-4977`."""
        workspace, run_id, _ = ran

        result = _replay(workspace, monkeypatch, run_id)

        assert result.exit_code == 0, result.output
        original = _artifacts(workspace / "runs" / run_id)
        assert any(name.startswith(f"describe/{INC_4977}/") for name in original)
        assert _artifacts(_replayed(workspace, run_id)) == original

    def test_a_conversion_cached_since_draws_nothing_in(self, ran, monkeypatch):
        """Row 4 — `INC-4977`'s `markdown`, made by a later run, is not read here."""
        workspace, run_id, model = ran
        _sources(workspace, " [markdown, page_images]")
        assert _cli(workspace, monkeypatch, "convert", PIPELINE).exit_code == 0
        later = _run(workspace, monkeypatch)
        assert later != run_id
        assert any(
            n.startswith(f"extract/{INC_4977}") for n in _artifacts(workspace / "runs" / later)
        )

        result = _replay(workspace, monkeypatch, run_id)

        assert result.exit_code == 0, result.output
        original = _artifacts(workspace / "runs" / run_id)
        assert not any(name.startswith(f"extract/{INC_4977}") for name in original)
        assert _artifacts(_replayed(workspace, run_id)) == original

    def test_a_container_the_run_could_not_read_is_not_pinned(self, workspace, monkeypatch):
        """Row 5, counter-example — the one R8.34 names: its pages never read."""
        model = _workspace(workspace, monkeypatch, layout={"manual": INC_4830})
        (container,) = [
            path
            for path in (workspace / ".dossier" / "cache" / "convert").rglob("*")
            if path.is_file()
            and not path.name.endswith(".meta.json")
            and path.read_bytes().startswith(MAGIC)
        ]
        container.write_bytes(container.read_bytes()[: len(MAGIC) + 5])
        result = _cli(workspace, monkeypatch, "run", PIPELINE)
        assert result.exit_code == 1, result.output
        run_id = sorted(p.name for p in (workspace / "runs").iterdir() if p.is_dir())[-1]

        replayed = _replay(workspace, monkeypatch, run_id)

        assert _pinned(workspace, run_id)[INC_4830]["kinds"] == ["markdown"]
        assert model.calls == ["text"]
        assert replayed.exit_code == 0, replayed.output
        assert _artifacts(_replayed(workspace, run_id)) == _artifacts(
            workspace / "runs" / run_id
        )

    def test_a_manifest_written_before_replays_as_before(self, workspace, monkeypatch):
        """Row 6, counter-example — no `kinds`: read as the converters pinned say."""
        _workspace(workspace, monkeypatch, layout={"manual": INC_4830})
        run_id = _run(workspace, monkeypatch)
        path = workspace / "runs" / run_id / "manifest.json"
        manifest = json.loads(path.read_text("utf-8"))
        for document in manifest["plan"]["documents"]:
            del document["kinds"]
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")

        result = _replay(workspace, monkeypatch, run_id)

        assert result.exit_code == 0, result.output
        original = _artifacts(workspace / "runs" / run_id)
        assert any(name.startswith(f"describe/{INC_4830}/") for name in original)
        assert _artifacts(_replayed(workspace, run_id)) == original
