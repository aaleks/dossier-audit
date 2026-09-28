"""R3.15 — a document's group is its key up to the first `/`.

The decision half of R3.15, and the reason `per_group` needs no configuration:
every connector already keys a file under what it belongs to. A Jira attachment
is `INC-4821/report.pdf` (R1.6), a Confluence file `81920114/escalation-matrix.png`
(R1.18), a folder's file its path under the folder. So the group is read off the
key, and a replay recomposes it from the keys its manifest pins (R4.15).

The CLI half -- one call per group -- is the acceptance test's.
"""

from __future__ import annotations

import pytest


def _group_of(key: str) -> str:
    from dossier.domain.groups import group_of

    return group_of(key)


class TestADocumentsGroupIsItsKeyUpToTheFirstSlash:
    """R3.15 — the group is the first segment of the key."""

    @pytest.mark.parametrize(
        ("key", "group"),
        [
            # Row 1: the one where a contract is a folder of files.
            ("ACME-2024/amendment-3.pdf", "ACME-2024"),
            # Row 3: the one where an attachment is filed under its issue, and
            # the issue itself -- a key with no `/` -- is the same group.
            ("INC-4821/report.pdf", "INC-4821"),
            ("INC-4821", "INC-4821"),
            # Row 5: the one where the folder goes two levels deep. The first
            # segment, not the last directory: an amendments/ subfolder is still
            # the contract's.
            ("ACME-2024/amendments/amendment-3.pdf", "ACME-2024"),
        ],
    )
    def test_the_group_is_the_key_up_to_its_first_slash(self, key: str, group: str):
        assert _group_of(key) == group

    def test_a_key_with_no_slash_is_a_group_of_its_own(self):
        """Row 8, a counter-example: the one with nothing to group.

        A flat folder is a folder of groups of one, each named by its key, so
        `per_group` over it asks exactly what `per_file` asks.
        """
        assert _group_of("PLAY-1001.md") == "PLAY-1001.md"

    def test_a_pages_pdf_export_is_not_the_pages_group(self):
        """Row 9, a counter-example: the one with a dot where a slash would be.

        Confluence keys a page's PDF export `81920114.pdf` (R1.19). Nothing in
        the key says it belongs to page `81920114`, and guessing from a file
        extension would be a second grouping rule nobody agreed (spec 003, open
        question 1).
        """
        assert _group_of("81920114.pdf") == "81920114.pdf"
        assert _group_of("81920114/escalation-matrix.png") == "81920114"


class TestAStepMayBeAskedPerGroup:
    """R3.15 — `per_group` is a mode a step may declare."""

    def test_a_step_declaring_per_group_loads(self):
        """Row 1's pipeline: the one where `extract` asks per contract.

        The fourth mode, beside `per_file`, `aggregate` and `per_part`. Before
        this rule the loader refused it by name, which is what the acceptance
        test first failed on.
        """
        from dossier.domain.pipeline import StepConfig

        step = StepConfig(
            id="extract",
            prompt="prompts/extract.md",
            input="documents",
            mode="per_group",
            output="schemas/incident.yaml",
        )

        assert step.mode == "per_group"


class TestAPerGroupStepIsAskedOncePerGroup:
    """R3.15 — `execute` fans a `per_group` step out over groups, not documents."""

    def test_four_documents_that_are_two_contracts_are_two_calls(self, tmp_path):
        """Rows 1 and 2: the one where four documents are two contracts.

        Two calls, each shown exactly its own members in key order, and two
        results named for the groups -- the unit a later step reads and a run
        reports, as a document is for `per_file`.
        """
        import json
        import re
        from datetime import UTC, datetime

        from tests.pipelines import prompt_for

        from dossier.application.run import RunInputs, execute
        from dossier.domain.fields import OutputSchema
        from dossier.domain.pipeline import PipelineConfig, StepConfig
        from dossier.infrastructure.cache import ArtifactCache

        shown: list[list[str]] = []

        class Model:
            model_id = "anthropic:claude-sonnet-4-5-20250929"

            def complete(self, prompt: str, *, schema=None, parts=()) -> str:
                members = re.findall(r'<document key="([^"]+)">', prompt)
                shown.append(members)
                return json.dumps({"document": members[0], "fields": []})

        keys = [
            "ACME-2024/amendment-1.md",
            "ACME-2024/amendment-3.md",
            "ACME-2024/master.md",
            "GLOBEX-2023/master.md",
        ]
        config = PipelineConfig(
            name="contract-renewal",
            sources=["contracts"],
            model=Model.model_id,
            steps=[
                StepConfig(
                    id="extract",
                    prompt="prompts/extract.md",
                    input="documents",
                    mode="per_group",
                )
            ],
        )

        report = execute(
            RunInputs(
                pipeline=config,
                pipeline_hash="0e52dd18" * 8,
                schemas={
                    "extract": OutputSchema(
                        schema={"type": "object"}, declaration_hash="6e0d4b27" * 8
                    )
                },
                prompts={"extract": prompt_for(["documents"])},
                documents={key: f"{index:064d}" for index, key in enumerate(keys)},
                document_text={key: f"# {key}\n" for key in keys},
            ),
            workspace=tmp_path,
            model=Model(),
            cache=ArtifactCache(tmp_path, namespace="stage"),
            run_id="20260806T142203Z-4f1a",
            started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
            dossier_version="0.1.0",
        )

        assert sorted(shown) == [keys[:3], keys[3:]]
        (step,) = report.steps
        assert [result.document for result in step.results] == ["ACME-2024", "GLOBEX-2023"]


class TestAPerGroupStepLineCountsGroups:
    """R3.15 row 1 — the step line counts what the step asked about."""

    def test_a_per_group_step_line_counts_groups(self):
        """The one where four documents are two contracts, said so.

        `4 document(s)` would be what the run read and not what it asked
        about; `2 document(s)` would be neither. The line counts the unit a
        call was made for, as it always has -- a group, here.
        """
        from dossier.domain.tracking import step_line

        line = step_line(step="extract", documents=2, cached=0, failed=0, unit="group")

        assert line == "extract: 2 group(s) · 0 from cache · 0 failed"

    def test_every_other_step_line_still_counts_documents(self):
        """A counter-example: the one where the step did not ask for groups."""
        from dossier.domain.tracking import step_line

        line = step_line(step="extract", documents=4, cached=0, failed=0)

        assert line == "extract: 4 document(s) · 0 from cache · 0 failed"
