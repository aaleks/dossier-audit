"""R8.34 — a parts container that cannot be unpacked is a document that did not
convert, named with why.

`run` told text from a container by trying to unpack it, so a container cut
short was passed over as if it were text: the document held no parts, the
`per_part` step skipped it, nothing was said and the run exited 0. Here
`INC-4830`'s postmortem is converted to `markdown` and `page_images`, and its
`page_images` container is cut short in the cache, past its first header: as a
disk, a copy or a person could leave it, since the cache does not check what
it reads back.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tests.acceptance.conftest import _cli
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, abstains

PIPELINE = "incident-audit"
SOURCE = "incidents-manual"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
POSTMORTEM = "INC-4830-postmortem-checkout-tls-expiry.pdf"
MAGIC = b"DOSSIER-PARTS 1\n"
LINE = (
    f"  {SOURCE}: {POSTMORTEM} could not be converted: "
    "its page_images container cannot be read: "
)


def _workspace(workspace: Path, monkeypatch):
    """The postmortem in a folder source, synced and converted; the model, answering nothing."""
    from tests.fakes import FakeModelClient

    import dossier.cli.bootstrap as cli

    inbox = workspace / "inbox" / "manual"
    inbox.mkdir(parents=True)
    shutil.copy(FIXTURES / "postmortems" / "pdf" / POSTMORTEM, inbox / POSTMORTEM)
    (workspace / "sources.yaml").write_text(
        f"sources:\n  - id: {SOURCE}\n    type: folder\n    path: inbox/manual/\n"
        "    convert:\n      application/pdf: [markdown, page_images]\n",
        encoding="utf-8",
    )
    write_pipeline(
        workspace,
        name=PIPELINE,
        sources=[SOURCE],
        inputs={"extract": "documents@page_images"},
        modes={"extract": "per_part"},
    )
    page = json.dumps({"document": POSTMORTEM, "fields": [abstains(f) for f in FIELDS]})
    model = FakeModelClient(responses=[page] * 10)
    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model, raising=False)
    for command in ("sync", "convert"):
        assert _cli(workspace, monkeypatch, command, PIPELINE).exit_code == 0
    return model


def _containers(workspace: Path) -> list[Path]:
    entries = (workspace / ".dossier" / "cache" / "convert").rglob("*")
    return [
        path
        for path in entries
        if path.is_file()
        and not path.name.endswith(".meta.json")
        and path.read_bytes().startswith(MAGIC)
    ]


class TestADamagedPartsContainerIsADocumentThatDidNotConvert:
    """R8.34 — named with why, and the run exits non-zero."""

    def test_a_container_cut_short_is_named_and_asked_nothing(
        self, workspace: Path, monkeypatch
    ):
        """Row 1 — the one whose `page_images` container ends inside a header."""
        model = _workspace(workspace, monkeypatch)
        (container,) = _containers(workspace)
        container.write_bytes(container.read_bytes()[: len(MAGIC) + 5])

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 1, result.output
        named = [line for line in result.stderr.splitlines() if line.startswith(LINE)]
        assert len(named) == 1, result.stderr
        assert model.call_count == 0

    def test_a_whole_container_is_asked_about_and_text_is_not_named(
        self, workspace: Path, monkeypatch
    ):
        """Rows 2 and 3, counter-examples — the `markdown` artifact, and the container whole."""
        model = _workspace(workspace, monkeypatch)

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert "could not be converted" not in result.stderr
        assert model.call_count == 3
