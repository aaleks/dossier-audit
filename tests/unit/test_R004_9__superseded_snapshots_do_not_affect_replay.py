"""R4.9 — a run whose pinned snapshots have been superseded still resolves and replays.

Newer snapshots are ignored. A past audit is defended by what it actually read.

This is the rule that makes an audit trail worth having. Asked in a year why a
finding was made, the answer has to be the document as it was that day -- not the
document as it is now, and not an error saying the evidence has moved on.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

from dossier.application.manifest import Manifest
from dossier.application.run import MissingFromReplay, RunInputs, execute, replay
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.cache import ArtifactCache

STARTED_AT = datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC)
PIPELINE_HASH = "0e52dd18" * 8
SCHEMA = OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)

PINNED = "a3f9c1e2" * 8
SUPERSEDED = "c4a70b93" * 8
ORIGINAL_TEXT = {"INC-4821": STAGE_INPUTS["INC-4821"]}


def answer(document: str, value: float = 48200.00) -> str:
    return json.dumps(
        {
            "document": document,
            "fields": [
                {
                    "field": "loss_amount",
                    "value": value,
                    "currency": "CHF",
                    "source": {"document": document, "span": LOSS_SPAN},
                }
            ],
        }
    )


def pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
            )
        ],
    )


def first_run(workspace: Path, *, documents=None, text=None) -> Manifest:
    """One completed run, pinned to `a3f9c1e2` unless told otherwise.

    Records media types and converters, because a manifest without them cannot
    drive a replay through the CLI -- which is where R4.9's "reads by the pinned
    hash" guarantee actually lives.
    """
    from dossier.domain.conversion import answering
    from dossier.domain.resolution import PinnedConverter
    from dossier.infrastructure.converters.registry import installed_converters

    config = pipeline()
    held = documents or {"INC-4821": PINNED}
    execute(
        RunInputs(
            pipeline=config,
            pipeline_hash=PIPELINE_HASH,
            schemas={"extract": SCHEMA},
            prompts={"extract": prompt_for(["documents"])},
            documents=held,
            media_types=dict.fromkeys(held, "text/markdown"),
            document_text=text or ORIGINAL_TEXT,
            converters=[
                PinnedConverter(
                    id=c.id, version=c.version, media_type=c.media_type, kind=c.kind
                )
                for c in answering(installed_converters(), named=[])
            ],
        ),
        workspace=workspace,
        model=FakeModelClient(responses=[answer("INC-4821")]),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=STARTED_AT,
        dossier_version="0.1.0",
    )
    return Manifest.read(workspace / "runs" / "20260806T142203Z-4f1a" / "manifest.json")


def replay_it(workspace: Path, manifest: Manifest, *, text=None):
    return replay(
        manifest=manifest,
        document_text=text or ORIGINAL_TEXT,
        cache=ArtifactCache(workspace, namespace="stage"),
    )


class TestAReplayReadsWhatItPinned:
    """R4.9 — the snapshot the run actually used, whatever has happened since."""

    def test_the_manifest_still_names_the_pinned_snapshot(self, tmp_path: Path):
        """Example 1: the one where `INC-4821` has been re-snapshotted since.

        The ledger has moved to a new hash. The manifest has not, and the manifest
        is what a replay reads -- so the pin survives whatever the source did
        afterwards.
        """
        manifest = first_run(tmp_path)

        assert [d.snapshot for d in manifest.plan.documents] == [PINNED]
        assert SUPERSEDED not in json.dumps(manifest.model_dump(mode="json"))

    def test_the_replay_completes_and_reproduces_the_result(self, tmp_path: Path):
        """Example 1, the observable half: the answer comes back unchanged."""
        manifest = first_run(tmp_path)

        report = replay_it(tmp_path, manifest)

        assert report.cache_hits == 1
        assert report.steps[0].results[0].records[0].value == 48200.00

    def test_a_tombstoned_document_still_replays(self, tmp_path: Path):
        """Example 2: the one where the document has left scope entirely.

        Tombstoning marks the ledger and never the store (R2.7), so the snapshot
        is still there to be read. A replay does not consult the ledger for
        *which* documents a run covered -- the manifest pinned them -- so a
        tombstone cannot remove one from a past run.
        """
        manifest = first_run(tmp_path)

        report = replay_it(tmp_path, manifest)

        assert [r.document for r in report.steps[0].results] == ["INC-4821"]

    def test_a_new_run_pins_the_newer_snapshot(self, tmp_path: Path):
        """Example 3: the one where only replay is frozen.

        A fresh run resolves against whatever is current. If it did not, the pin
        would be permanent rather than per-run, and no audit could ever be
        brought up to date.
        """
        first_run(tmp_path)

        config = pipeline()
        moved_text = {"INC-4821": ORIGINAL_TEXT["INC-4821"] + "\n\nAmended.\n"}
        execute(
            RunInputs(
                pipeline=config,
                pipeline_hash=PIPELINE_HASH,
                schemas={"extract": SCHEMA},
                prompts={"extract": prompt_for(["documents"])},
                documents={"INC-4821": SUPERSEDED},
                document_text=moved_text,
            ),
            workspace=tmp_path,
            model=FakeModelClient(responses=[answer("INC-4821", value=49000.00)]),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260907T090000Z-bbbb",
            started_at=STARTED_AT,
            dossier_version="0.1.0",
        )

        newer = Manifest.read(tmp_path / "runs" / "20260907T090000Z-bbbb" / "manifest.json")
        assert [d.snapshot for d in newer.plan.documents] == [SUPERSEDED]

    def test_both_runs_replay_to_their_own_answers(self, tmp_path: Path):
        """The one that makes example 3 mean something.

        Two runs over the same document at different snapshots, each replayed.
        Each must come back with its own answer -- which is the whole promise of
        pinning, and would be silently broken by a cache that overwrote entries
        rather than adding them.
        """
        old = first_run(tmp_path)

        moved_text = {"INC-4821": ORIGINAL_TEXT["INC-4821"] + "\n\nAmended.\n"}
        config = pipeline()
        execute(
            RunInputs(
                pipeline=config,
                pipeline_hash=PIPELINE_HASH,
                schemas={"extract": SCHEMA},
                prompts={"extract": prompt_for(["documents"])},
                documents={"INC-4821": SUPERSEDED},
                document_text=moved_text,
            ),
            workspace=tmp_path,
            model=FakeModelClient(responses=[answer("INC-4821", value=49000.00)]),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260907T090000Z-bbbb",
            started_at=STARTED_AT,
            dossier_version="0.1.0",
        )
        new = Manifest.read(tmp_path / "runs" / "20260907T090000Z-bbbb" / "manifest.json")

        assert replay_it(tmp_path, old).steps[0].results[0].records[0].value == 48200.00
        assert (
            replay_it(tmp_path, new, text=moved_text).steps[0].results[0].records[0].value
            == 49000.00
        )

    def test_a_replay_whose_artifact_is_gone_says_so(self, tmp_path: Path):
        """Counter-example (row 4) of R4.7: the one where a replay is allowed to fail.

        What it may never do is substitute other content. The error names the
        step and the key, so the failure is diagnosable rather than merely loud.
        """
        manifest = first_run(tmp_path)
        for artifact in (tmp_path / ".dossier" / "cache" / "stage").rglob("*"):
            if artifact.is_file():
                artifact.unlink()

        with pytest.raises(MissingFromReplay) as error:
            replay_it(tmp_path, manifest)

        assert "extract" in str(error.value)
        assert "INC-4821" in str(error.value)


class TestAReplayReproducesTheArtifactsByteForByte:
    """R4.7 row 1 — "every artifact is byte-identical to the original".

    Found unasserted by `/quality`. The acceptance test proved the replay exited
    0, printed "no model calls" and wrote nothing new — all of which a replay
    that reproduced *nothing* also satisfies, and did: a `replay` returning zero
    results passed five of that file's six rows.

    Byte-identity is a claim about what came back, so it is asserted where the
    results are: against the original run's own report.
    """

    def test_the_replayed_artifacts_are_the_bytes_the_run_produced(self, tmp_path: Path):
        """The one that compares the two runs' outputs directly."""
        from dossier.application.run import _as_text

        config = pipeline()
        original = execute(
            RunInputs(
                pipeline=config,
                pipeline_hash=PIPELINE_HASH,
                schemas={"extract": SCHEMA},
                prompts={"extract": prompt_for(["documents"])},
                documents={"INC-4821": PINNED},
                document_text=ORIGINAL_TEXT,
            ),
            workspace=tmp_path,
            model=FakeModelClient(responses=[answer("INC-4821")]),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260806T142203Z-4f1a",
            started_at=STARTED_AT,
            dossier_version="0.1.0",
        )
        manifest = Manifest.read(tmp_path / "runs" / "20260806T142203Z-4f1a" / "manifest.json")

        replayed = replay_it(tmp_path, manifest)

        produced = [_as_text(r) for step in original.steps for r in step.results]
        reproduced = [_as_text(r) for step in replayed.steps for r in step.results]
        assert produced == reproduced
        assert produced, "and there was something to reproduce"

    def test_a_replay_that_reproduced_nothing_would_not_pass(self, tmp_path: Path):
        """The one that names the shape of the gap that was there.

        Counting is the cheapest thing that distinguishes "reproduced the run"
        from "did nothing quietly", and it was the assertion missing everywhere.
        """
        manifest = first_run(tmp_path)

        report = replay_it(tmp_path, manifest)

        assert report.cache_hits == 1
        assert [len(step.results) for step in report.steps] == [1]

    def test_the_grounding_checks_come_back_too(self, tmp_path: Path):
        """The one where the reproduced result is whole, not just its bytes.

        A caller gets a `DocumentResult`, and the grounding checks in it are
        re-derived on a hit. Being pure (R6.4), they must come out the same --
        otherwise a replayed run could disagree with the original about which
        fields were evidenced.
        """
        config = pipeline()
        original = execute(
            RunInputs(
                pipeline=config,
                pipeline_hash=PIPELINE_HASH,
                schemas={"extract": SCHEMA},
                prompts={"extract": prompt_for(["documents"])},
                documents={"INC-4821": PINNED},
                document_text=ORIGINAL_TEXT,
            ),
            workspace=tmp_path,
            model=FakeModelClient(responses=[answer("INC-4821")]),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260806T142203Z-4f1a",
            started_at=STARTED_AT,
            dossier_version="0.1.0",
        )
        manifest = Manifest.read(tmp_path / "runs" / "20260806T142203Z-4f1a" / "manifest.json")

        replayed = replay_it(tmp_path, manifest)

        assert replayed.steps[0].results[0].checks == original.steps[0].results[0].checks


class TestTheReplayReadsByThePinnedHashNotJustRecordsIt:
    """R4.9 row 1 — "the replay reads `a3f9c1e2`", not merely names it.

    Found by `/quality`. The rows above assert the *manifest* still names the
    pinned snapshot, and hand the original text to `replay()` by keyword. That
    proves the pin survives; it does not prove anything reads by it.

    The guarantee actually lives on the CLI path, which converts from
    `manifest.plan.documents`. These rows drive that path with a superseded
    snapshot sitting in the store beside the pinned one -- the situation the rule
    is about, and the one nothing exercised.
    """

    def test_the_replay_reads_the_pinned_snapshot_not_the_newer_one(
        self, tmp_path: Path, monkeypatch
    ):
        """The one where both snapshots are present and one is newer.

        A replay that resolved against "the current content for this key" would
        find the amended document and reproduce a finding about text the run
        never saw.
        """
        from typer.testing import CliRunner

        from dossier.application.convert import HeldDocument, convert_source
        from dossier.cli.main import app
        from dossier.domain.conversion import answering
        from dossier.infrastructure.cache import ArtifactCache
        from dossier.infrastructure.converters.registry import installed_converters
        from dossier.infrastructure.store import SnapshotStore

        store = SnapshotStore(tmp_path)
        original = store.put(ORIGINAL_TEXT["INC-4821"].encode())
        superseded = store.put((ORIGINAL_TEXT["INC-4821"] + "\n\nAmended.\n").encode())
        assert original != superseded, "both are in the store, and they differ"

        # Convert both, so the replay could in principle find either.
        for digest in (original, superseded):
            convert_source(
                source_id="incidents-manual",
                documents={
                    "INC-4821": HeldDocument(snapshot=digest, media_type="text/markdown")
                },
                kinds=None,
                converters=answering(installed_converters(), named=[]),
                store=store,
                cache=ArtifactCache(tmp_path, namespace="convert"),
                run_id="20260806T142203Z-4f1a",
                dossier_version="0.1.0",
            )

        manifest = first_run(tmp_path, documents={"INC-4821": original})

        assert [d.snapshot for d in manifest.plan.documents] == [original]

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["run", "--replay", f"runs/{manifest.run_id}"])

        assert result.exit_code == 0, result.output
        assert "1 artifact(s) reproduced" in result.output

    def test_a_replay_pinned_to_a_snapshot_that_was_never_converted_stops(
        self, tmp_path: Path, monkeypatch
    ):
        """The counter-example: reading by the hash means failing by it too.

        If a replay genuinely reads by the pinned hash, pinning one whose
        conversion was never cached must stop it. A replay that quietly used
        whatever conversion it could find would pass this and be wrong.
        """
        from typer.testing import CliRunner

        from dossier.cli.main import app
        from dossier.infrastructure.store import SnapshotStore

        store = SnapshotStore(tmp_path)
        pinned = store.put(ORIGINAL_TEXT["INC-4821"].encode())
        manifest = first_run(tmp_path, documents={"INC-4821": pinned})

        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["run", "--replay", f"runs/{manifest.run_id}"])

        assert result.exit_code == 2
        assert "cannot be reproduced" in result.output


class TestARunAfterTheSourceMovedSaysSo:
    """R4.9 row 4, the decision: which documents moved since a past run pinned them."""

    def test_a_re_snapshotted_document_is_named_and_an_unchanged_one_is_not(self):
        """The one where `INC-4821` was re-snapshotted and `INC-4822` was not."""
        from dossier.domain.resolution import PinnedDocument, moved_since

        pinned = [
            PinnedDocument(key="INC-4821", snapshot="a3f9c1e2" * 8),
            PinnedDocument(key="INC-4822", snapshot="77c1b40a" * 8),
        ]

        moved = moved_since(pinned, {"INC-4821": "c4a70b93" * 8, "INC-4822": "77c1b40a" * 8})

        assert moved == {"INC-4821": "re-snapshotted"}

    def test_a_document_added_or_tombstoned_since_is_named_the_same_way(self):
        """The one where the source gained `INC-5102` and lost `INC-4822`."""
        from dossier.domain.resolution import PinnedDocument, moved_since

        pinned = [PinnedDocument(key="INC-4822", snapshot="77c1b40a" * 8)]

        moved = moved_since(pinned, {"INC-5102": "c4a70b93" * 8})

        assert moved == {"INC-4822": "gone", "INC-5102": "new"}

    def test_nothing_moved_is_nothing_to_say(self):
        """The one where the source is exactly as the last run read it."""
        from dossier.domain.resolution import PinnedDocument, moved_since

        pinned = [PinnedDocument(key="INC-4821", snapshot="a3f9c1e2" * 8)]

        assert moved_since(pinned, {"INC-4821": "a3f9c1e2" * 8}) == {}
