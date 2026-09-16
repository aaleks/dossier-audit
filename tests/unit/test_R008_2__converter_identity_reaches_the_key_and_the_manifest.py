"""R8.2 — a converter declares an id and a version, and both appear in every convert
key and every manifest.

The id names the thing; the version names its behaviour. Both enter every convert
key and every provenance record, which is what makes raising a version invalidate
exactly the artifacts that converter produced and nothing else (R5.4).

A converter that declares no version is refused where it is registered. Letting it
through would put `None` in a key that R5.4 has to act on, and the failure would
surface as an unexplained cache miss -- or worse, an unexplained cache *hit* --
long after the package was installed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import FakeModelClient
from tests.grounding_fixtures import LOSS_SPAN, STAGE_INPUTS
from tests.pipelines import prompt_for

import dossier.infrastructure.converters.registry as registry
from dossier.application.manifest import Manifest
from dossier.application.run import execute
from dossier.domain.fields import OutputSchema
from dossier.domain.keys import ConvertInputs, cache_key, provenance
from dossier.domain.resolution import PinnedConverter
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.converters.registry import installed_converters

pytestmark = pytest.mark.outer_loop

# `OPS-114` as spec 008's worked example converts it: a PDF at `b81f0c6d`,
# through `pdf-markdown` `1.3.0`.
SNAPSHOT = "b81f0c6d" * 8
RUN_ID = "20260806T142203Z-4f1a"
MODEL = "anthropic:claude-sonnet-4-5-20250929"


class PdfMarkdown:
    id = "pdf-markdown"
    version = "1.3.0"
    media_type = "application/pdf"
    kind = "markdown"

    def convert(self, payload: bytes, options) -> bytes:
        return b"# " + payload


class Undeclared:
    """A converter with an id and no version, as a careless package would ship one."""

    id = "pdf-images"
    media_type = "application/pdf"
    kind = "page_images"

    def convert(self, payload: bytes, options) -> bytes:
        return b"PNG"


class StubEntryPoint:
    """One `dossier.converters` entry point, as an installed package declares it."""

    def __init__(self, converter: type) -> None:
        self.name = converter.id
        self.group = registry.ENTRY_POINT_GROUP
        self._converter = converter

    def load(self) -> type:
        return self._converter


def installed(monkeypatch, *converters: type) -> None:
    monkeypatch.setattr(
        registry,
        "entry_points",
        lambda group: (
            [StubEntryPoint(c) for c in converters]
            if group == registry.ENTRY_POINT_GROUP
            else []
        ),
    )


def convert_inputs(**overrides) -> ConvertInputs:
    fields = {
        "snapshot": SNAPSHOT,
        "converter_id": "pdf-markdown",
        "converter_version": "1.3.0",
    }
    return ConvertInputs(**{**fields, **overrides})


def answer() -> str:
    return json.dumps(
        {
            "document": "INC-4821",
            "fields": [
                {
                    "field": "loss_amount",
                    "value": 48200.00,
                    "currency": "CHF",
                    "source": {"document": "INC-4821", "span": LOSS_SPAN},
                }
            ],
        }
    )


def run(workspace: Path, converters: list[PinnedConverter]) -> Manifest:
    """One run of `incident-audit`, and the manifest it wrote."""
    from dossier.domain.pipeline import PipelineConfig, StepConfig

    config = PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
            )
        ],
    )
    execute(
        workspace=workspace,
        pipeline=config,
        pipeline_hash="0e52dd18" * 8,
        documents={"INC-4821": "a3f9c1e2" * 8},
        media_types={"INC-4821": "application/pdf"},
        document_text=STAGE_INPUTS,
        schemas={
            "extract": OutputSchema(schema={"type": "object"}, declaration_hash="6e0d4b27" * 8)
        },
        prompts={"extract": prompt_for(["documents"])},
        model=FakeModelClient(responses=[answer()]),
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id=RUN_ID,
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        converters=converters,
    )
    return Manifest.read(workspace / "runs" / RUN_ID / "manifest.json")


class TestConverterIdentityReachesTheKeyAndTheManifest:
    """R8.2 — the id and the version are in every convert key and every manifest."""

    def test_the_key_and_the_record_name_the_snapshot_the_id_and_the_version(self):
        """Example 1: the one where `OPS-114` is converted by `pdf-markdown` `1.3.0`.

        All three are load-bearing: changing any one of them alone moves the key,
        and the record beside the artifact names each of them.
        """
        inputs = convert_inputs()
        baseline = cache_key(inputs)

        moved = [
            convert_inputs(snapshot="a3f9c1e2" * 8),
            convert_inputs(converter_id="pdf-images"),
            convert_inputs(converter_version="1.4.0"),
        ]
        for changed in moved:
            assert cache_key(changed) != baseline

        record = provenance(inputs, run_id=RUN_ID, dossier_version="0.1.0")
        assert record["snapshot"] == SNAPSHOT
        assert record["converter_id"] == "pdf-markdown"
        assert record["converter_version"] == "1.3.0"

    def test_the_manifest_lists_every_converter_with_its_version(self, tmp_path: Path):
        """Example 2: the one where the manifest is read after the run.

        Listed with versions, so the run is reproducible without the installed
        packages agreeing with it (spec 004): a replay reads what that afternoon
        used, not what is installed today.
        """
        pinned = [
            PinnedConverter(
                id="pdf-markdown",
                version="1.3.0",
                media_type="application/pdf",
                kind="markdown",
            ),
            PinnedConverter(
                id="markdown-text", version="1.0.0", media_type="text/markdown", kind="markdown"
            ),
        ]

        manifest = run(tmp_path, pinned)

        assert [(c.id, c.version) for c in manifest.plan.converters] == [
            ("pdf-markdown", "1.3.0"),
            ("markdown-text", "1.0.0"),
        ]

    def test_raising_the_version_moves_every_key_that_converter_produced(self):
        """Example 3: the one where `pdf-markdown` goes `1.3.0` -> `1.4.0` (R5.4)."""
        snapshots = ["b81f0c6d" * 8, "a3f9c1e2" * 8, "77c1b40a" * 8]

        before = [cache_key(convert_inputs(snapshot=s)) for s in snapshots]
        after = [
            cache_key(convert_inputs(snapshot=s, converter_version="1.4.0")) for s in snapshots
        ]

        assert not set(before) & set(after)

    def test_a_converter_with_no_version_is_refused_at_registration(self, monkeypatch):
        """Counter-example (row 4): the one declaring an id and no version.

        Refused where it is registered, naming the converter and what it is
        missing. A converter with no version cannot be invalidated, so R5.4 has
        nothing to act on -- and a key built over a missing version would fail
        much later, as a cache result nobody can explain.
        """
        installed(monkeypatch, PdfMarkdown, Undeclared)

        with pytest.raises(ValueError) as error:
            installed_converters()

        message = str(error.value)
        assert "pdf-images" in message
        assert "version" in message
        assert registry.ENTRY_POINT_GROUP in message

    def test_a_fully_declared_converter_still_registers(self, monkeypatch):
        """The other half of row 4: the check refuses the broken one only."""
        installed(monkeypatch, PdfMarkdown)

        (converter,) = installed_converters()

        assert (converter.id, converter.version) == ("pdf-markdown", "1.3.0")
