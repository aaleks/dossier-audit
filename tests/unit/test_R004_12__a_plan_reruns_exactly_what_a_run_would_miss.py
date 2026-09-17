"""R4.12 — `--plan` reports a step as re-running exactly when a run would miss
its cache. The decision.

Two resolved plans in, one line per step out, compared over exactly what enters
a stage key -- inputs, prompt hash, declaration hash -- and nothing else. The
pipeline hash is deliberately absent from the comparison (R4.5), and so is
anything dossier itself says to a model (R0.5 row 5).
"""

from __future__ import annotations

from dossier.domain.plan import StepStatus, diff
from dossier.domain.resolution import ResolvedPlan, ResolvedStep

MODEL = "anthropic:claude-sonnet-4-5-20250929"
PROMPT = "0e52dd18" * 8
EDITED_PROMPT = "c4a70b93" * 8
DECLARATION = "6e0d4b27" * 8
EDITED_DECLARATION = "d24c86e1" * 8


def _plan(
    *,
    pipeline_hash: str = "b81f0c6d" * 8,
    verify_prompt: str = PROMPT,
    declaration: str = DECLARATION,
) -> ResolvedPlan:
    """`extract` -> `verify` -> `report`, each keyed on its prompt and the declaration."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash=pipeline_hash,
        model=MODEL,
        steps=[
            ResolvedStep(
                id="extract", inputs=["documents"], prompt_hash=PROMPT, schema_hash=declaration
            ),
            ResolvedStep(
                id="verify",
                inputs=["documents", "extract"],
                prompt_hash=verify_prompt,
                schema_hash=declaration,
            ),
            ResolvedStep(id="report", inputs=["verify"], prompt_hash=PROMPT, schema_hash=None),
        ],
        documents=[],
    )


def _statuses(current: ResolvedPlan, previous: ResolvedPlan) -> dict[str, StepStatus]:
    return {line.step.id: line.status for line in diff(current, previous)}


class TestAPlanRerunsExactlyWhatARunWouldMiss:
    """R4.12 — `cached` is a promise the run keeps."""

    def test_an_edited_prompt_reruns_that_step_and_what_reads_it(self):
        """Example 1: the one where `prompts/02_verify.md` was edited.

        `verify` for its own prompt, `report` because what it reads will
        change, `extract` untouched -- exactly the steps a run would re-ask
        (R5.2).
        """
        statuses = _statuses(_plan(verify_prompt=EDITED_PROMPT), _plan())

        assert statuses == {
            "extract": StepStatus.CACHED,
            "verify": StepStatus.PROMPT_CHANGED,
            "report": StepStatus.UPSTREAM_CHANGED,
        }

    def test_an_edited_declaration_reruns_every_step_declaring_it(self):
        """Example 2: the one where `schemas/incident.yaml` was edited (R6.11)."""
        statuses = _statuses(_plan(declaration=EDITED_DECLARATION), _plan())

        assert statuses["extract"] is StepStatus.DECLARATION_CHANGED
        assert statuses["verify"] is StepStatus.DECLARATION_CHANGED
        assert statuses["report"] is StepStatus.UPSTREAM_CHANGED, (
            "declares nothing; reads verify"
        )

    def test_a_comment_in_the_pipeline_file_changes_nothing(self):
        """Example 3: the one where only the pipeline hash moved (R4.5)."""
        statuses = _statuses(_plan(pipeline_hash="a3f9c1e2" * 8), _plan())

        assert set(statuses.values()) == {StepStatus.CACHED}

    def test_what_dossier_itself_says_is_in_no_plan(self):
        """Counter-example (row 4): the one where dossier's retry wrapper was edited.

        Nothing in a resolved plan carries it, because nothing in a key does
        (R0.5 row 5); two plans resolved before and after such an edit are the
        same plan, and every step stays `cached`.
        """
        before, after = _plan(), _plan()

        assert before == after
        assert set(_statuses(after, before).values()) == {StepStatus.CACHED}
