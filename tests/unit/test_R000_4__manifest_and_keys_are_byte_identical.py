"""R0.4 — the resolved manifest and every cache key are byte-identical across runs and machines.

Given the same snapshots, prompts, schemas and model identifier, resolution and
key computation produce identical bytes in any process, on any machine, under
any locale or timezone.

Rows 2 and 3 have to be real processes. `PYTHONHASHSEED` is read at interpreter
start, and a timezone set inside this process after `time` has initialised
proves nothing, so a probe computes the resolved plan, a stage key and a convert
key in a fresh interpreter under each environment, and the outputs are compared.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from dossier.domain.keys import ArtifactInput, ConvertInputs, StageInputs, cache_key, provenance
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.resolution import resolve

PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}
MODEL = "anthropic:claude-sonnet-4-5-20250929"

VERIFY = StageInputs(
    step="verify",
    prompt=ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8),
    output_schema=ArtifactInput(
        role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8
    ),
    model=MODEL,
    inputs=[
        ArtifactInput(role="documents", path="converted/INC-4821.md", hash="5d3ba0f7" * 8),
        ArtifactInput(role="extract", path="extract/INC-4821.json", hash="77c1b40a" * 8),
    ],
)
CONVERT = ConvertInputs(
    snapshot="a3f9c1e2" * 8, converter_id="markdown-text", converter_version="1.0.0"
)


def incident_audit() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="verify", prompt="prompts/02_verify.md", input="previous", mode="per_file"
            ),
        ],
    )


PROBE = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, {src!r})
    from dossier.domain.keys import ArtifactInput, ConvertInputs, StageInputs, cache_key
    from dossier.domain.pipeline import PipelineConfig, StepConfig
    from dossier.domain.resolution import resolve

    stage = StageInputs.model_validate_json({stage!r})
    convert = ConvertInputs.model_validate_json({convert!r})
    plan = resolve(
        pipeline=PipelineConfig.model_validate_json({pipeline!r}),
        pipeline_hash={pipeline_hash!r},
        documents={documents!r},
    )
    sys.stdout.write(json.dumps({{
        "stage": cache_key(stage),
        "convert": cache_key(convert),
        "plan": plan.model_dump_json(),
    }}))
    """
)


def probe(repo_root: Path, **environment: str) -> dict[str, str]:
    """The plan and both keys, as a fresh interpreter under `environment` computes them."""
    source = PROBE.format(
        src=str(repo_root / "src"),
        stage=VERIFY.model_dump_json(),
        convert=CONVERT.model_dump_json(),
        pipeline=incident_audit().model_dump_json(),
        pipeline_hash=PIPELINE_HASH,
        documents=DOCUMENTS,
    )
    completed = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "", **environment},
        cwd=str(repo_root),
    )
    return json.loads(completed.stdout)


class TestManifestAndKeysAreByteIdentical:
    """R0.4 — the resolved manifest and every cache key are byte-identical everywhere."""

    def test_resolving_twice_in_one_process_is_identical(self):
        """Example 1: the one where `incident-audit` is resolved twice in one process.

        Identical bytes, with nothing to exclude: the run id and the start time
        are not on the resolved plan at all (R4.8), so there is no comparison
        to remember to exempt them from.
        """
        first = resolve(
            pipeline=incident_audit(), pipeline_hash=PIPELINE_HASH, documents=DOCUMENTS
        )
        second = resolve(
            pipeline=incident_audit(), pipeline_hash=PIPELINE_HASH, documents=DOCUMENTS
        )

        assert first.model_dump_json().encode() == second.model_dump_json().encode()

    def test_two_timezones_compute_the_same_keys(self, repo_root: Path):
        """Example 2: the one run under `TZ=UTC` and under `TZ=Asia/Tokyo`."""
        in_utc = probe(repo_root, TZ="UTC", PYTHONHASHSEED="0")
        in_tokyo = probe(repo_root, TZ="Asia/Tokyo", PYTHONHASHSEED="0")

        assert in_tokyo == in_utc

    def test_two_hash_seeds_compute_the_same_keys(self, repo_root: Path):
        """Example 3: the one in two processes with different `PYTHONHASHSEED`.

        A `hash()` or a set iterated into a key would reorder under a different
        seed, and the keys would stop matching between two runs on one machine.
        """
        seeded = probe(repo_root, PYTHONHASHSEED="0")
        reseeded = probe(repo_root, PYTHONHASHSEED="12345")

        assert reseeded == seeded
        assert seeded["stage"] == cache_key(VERIFY)
        assert seeded["convert"] == cache_key(CONVERT)

    def test_the_run_id_is_recorded_but_never_keyed(self):
        """Counter-example (row 4): the one with run id `20260806T142203Z-4f1a`.

        It differs between runs by design, so it may appear in a record and in
        no key. The inputs a key is taken over refuse it outright: a field the
        key does not know about is how a record and a key drift apart (R5.1).
        """
        first = provenance(VERIFY, run_id="20260806T142203Z-4f1a", dossier_version="0.1.0")
        second = provenance(VERIFY, run_id="20260907T090000Z-bbbb", dossier_version="0.1.0")

        assert first["run_id"] != second["run_id"]
        assert first["cache_key"] == second["cache_key"] == cache_key(VERIFY)
        for inputs in (VERIFY, CONVERT):
            with pytest.raises(ValidationError):
                type(inputs)(**inputs.model_dump(), run_id="20260806T142203Z-4f1a")
