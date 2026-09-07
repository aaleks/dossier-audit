"""R4.8 — resolving the same pipeline twice produces a byte-identical manifest.

Apart from the run id and the start time, which are the only two fields that
record when rather than what. Here they are not excluded from a comparison --
they are not on `ResolvedPlan` at all, so there is nothing to forget to exclude.

This is the rule that makes a cache trustworthy. If resolution varied between
processes, every key derived from it would vary too, and a cache would hit on
the machine that wrote it and miss everywhere else (R5.6).

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.domain.resolution import resolve

PIPELINE_HASH = "0e52dd18" * 8
DOCUMENTS = {"INC-4821": "a3f9c1e2" * 8, "INC-4822": "77c1b40a" * 8}


def pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-manual"],
        model="anthropic:claude-sonnet-4-5-20250929",
        steps=[
            StepConfig(id="extract", prompt="prompts/01_extract.md", input="documents",
                       mode="per_file"),
            StepConfig(id="verify", prompt="prompts/01_extract.md", input="previous",
                       mode="per_file"),
        ],
    )


def resolved_bytes(documents=None) -> bytes:
    plan = resolve(
        pipeline=pipeline(),
        pipeline_hash=PIPELINE_HASH,
        documents=DOCUMENTS if documents is None else documents,
    )
    return plan.model_dump_json().encode("utf-8")


# Run in a subprocess so PYTHONHASHSEED is actually different -- it is read at
# interpreter start, so setting it inside this process would prove nothing.
PROBE = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {src!r})
    from dossier.domain.pipeline import PipelineConfig, StepConfig
    from dossier.domain.resolution import resolve

    plan = resolve(
        pipeline=PipelineConfig(
            name="incident-audit",
            sources=["incidents-manual"],
            model="anthropic:claude-sonnet-4-5-20250929",
            steps=[
                StepConfig(id="extract", prompt="p.md", input="documents", mode="per_file"),
                StepConfig(id="verify", prompt="p.md", input="previous", mode="per_file"),
            ],
        ),
        pipeline_hash={hash!r},
        documents={documents!r},
    )
    sys.stdout.write(plan.model_dump_json())
    """
)


class TestResolutionIsByteIdentical:
    """R4.8 — the same inputs resolve to the same bytes, anywhere."""

    def test_resolving_twice_in_one_process_is_identical(self):
        """Example 1: the one that catches a stray clock or id."""
        assert resolved_bytes() == resolved_bytes()

    def test_two_processes_with_different_hash_seeds_agree(self, repo_root: Path):
        """Example 2: the one where set iteration order would leak.

        `PYTHONHASHSEED` is read at interpreter start, so this has to be two real
        processes. A single `set` anywhere in the resolution path reorders under
        a different seed, and the two outputs stop matching.
        """
        source = PROBE.format(
            src=str(repo_root / "src"), hash=PIPELINE_HASH, documents=DOCUMENTS
        )
        outputs = [
            subprocess.run(
                [sys.executable, "-c", source],
                capture_output=True,
                text=True,
                check=True,
                env={"PYTHONHASHSEED": seed, "PATH": ""},
                cwd=str(repo_root),
            ).stdout
            for seed in ("0", "12345")
        ]

        assert outputs[0] == outputs[1]

    def test_the_working_directory_does_not_leak_in(self, repo_root: Path, tmp_path: Path):
        """Example 3: the one where an absolute path would show up.

        Run from two different directories. A plan that recorded where it was
        resolved would differ, and would also stop matching on the machine that
        replays it (R4.7).
        """
        source = PROBE.format(
            src=str(repo_root / "src"), hash=PIPELINE_HASH, documents=DOCUMENTS
        )
        outputs = [
            subprocess.run(
                [sys.executable, "-c", source],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(directory),
            ).stdout
            for directory in (repo_root, tmp_path)
        ]

        assert outputs[0] == outputs[1]
        assert str(tmp_path) not in outputs[1]

    def test_documents_given_in_a_different_order_resolve_the_same(self):
        """The one where the caller's iteration order must not survive.

        The mapping comes from a ledger query, and a query returns rows in
        whatever order it likes. Two runs over the same snapshots are the same
        run (R5.6).
        """
        reversed_mapping = dict(reversed(list(DOCUMENTS.items())))

        assert resolved_bytes(reversed_mapping) == resolved_bytes()

    def test_a_changed_snapshot_changes_exactly_one_hash(self):
        """Counter-example (row 4): the one where the bytes are *supposed* to differ.

        Determinism is not sameness. A plan that did not move when a document
        moved would be worthless, so the difference is checked to be present and
        confined to the one document that changed.
        """
        moved = {**DOCUMENTS, "INC-4822": "b81f0c6d" * 8}

        before = resolve(pipeline=pipeline(), pipeline_hash=PIPELINE_HASH, documents=DOCUMENTS)
        after = resolve(pipeline=pipeline(), pipeline_hash=PIPELINE_HASH, documents=moved)

        assert before != after
        assert [d.key for d in before.documents] == [d.key for d in after.documents]
        differing = [
            b.key
            for b, a in zip(before.documents, after.documents, strict=True)
            if b.snapshot != a.snapshot
        ]
        assert differing == ["INC-4822"]
