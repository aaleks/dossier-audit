"""R4.12 — `--plan` reports a step as re-running exactly when a run would miss
its cache. The decision.

Two resolved plans in, one line per step out, compared over exactly what enters
a stage key -- inputs, prompt hash, declaration hash, the pinned model
identifier, and the converted text each step reads, which moves with a snapshot
or with the converter behind it -- and nothing else. The pipeline hash is
deliberately absent from the comparison (R4.5), and so is anything dossier
itself says to a model (R0.5 row 5).
"""

from __future__ import annotations

from dossier.domain.plan import StepStatus, diff
from dossier.domain.resolution import (
    PinnedConverter,
    PinnedDocument,
    ResolvedPlan,
    ResolvedStep,
)

MODEL = "anthropic:claude-sonnet-4-5-20250929"
ANOTHER_MODEL = "openai:gpt-5.4-mini"
PROMPT = "0e52dd18" * 8
EDITED_PROMPT = "c4a70b93" * 8
DECLARATION = "6e0d4b27" * 8
EDITED_DECLARATION = "d24c86e1" * 8
SNAPSHOT = "a3f9c1e2" * 8
NEW_SNAPSHOT = "5b1e77a4" * 8

CONVERTER = PinnedConverter(
    id="pdf-markdown", version="1.3.0", media_type="application/pdf", kind="markdown"
)


def _documents(**snapshots: str) -> list[PinnedDocument]:
    return [
        PinnedDocument(key=key, snapshot=snapshot, media_type="application/pdf")
        for key, snapshot in snapshots.items()
    ]


HELD = {"INC_4821": SNAPSHOT, "INC_4901": SNAPSHOT}


def _plan(
    *,
    pipeline_hash: str = "b81f0c6d" * 8,
    verify_prompt: str = PROMPT,
    declaration: str = DECLARATION,
    model: str = MODEL,
    documents: list[PinnedDocument] | None = None,
    converters: list[PinnedConverter] | None = None,
) -> ResolvedPlan:
    """`extract` -> `verify` -> `report`, each keyed on its prompt and the declaration."""
    return ResolvedPlan(
        pipeline="incident-audit",
        pipeline_hash=pipeline_hash,
        model=model,
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
        documents=_documents(**HELD) if documents is None else documents,
        converters=[CONVERTER] if converters is None else converters,
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

    def test_a_changed_model_identifier_reruns_every_step(self):
        """Example 4: the one where `model:` was changed to another pinned id.

        Every step, whatever it reads: the identifier is in every stage key
        (R5.3), so nothing is served. This is the case that printed `cached` and
        then asked the model four times.
        """
        statuses = _statuses(_plan(model=ANOTHER_MODEL), _plan())

        assert set(statuses.values()) == {StepStatus.MODEL_CHANGED}

    def test_a_resynced_document_reruns_the_steps_that_read_it(self):
        """Example 5: the one where `INC_4821` was re-synced to new bytes.

        `extract` and `verify` read `documents`; `report` reads only `verify`
        and is reached by upstream propagation. The moved documents are named,
        because "documents changed" over four thousand of them is not something
        a person can check.
        """
        moved = _plan(documents=_documents(INC_4821=NEW_SNAPSHOT, INC_4901=SNAPSHOT))

        lines = {line.step.id: line for line in diff(moved, _plan())}

        assert lines["extract"].status is StepStatus.DOCUMENTS_CHANGED
        assert lines["verify"].status is StepStatus.DOCUMENTS_CHANGED
        assert lines["report"].status is StepStatus.UPSTREAM_CHANGED
        assert lines["extract"].moved == ("INC_4821 changed",)

    def test_a_new_document_is_named_as_new(self):
        """Example 5's other half: a document the last run never saw.

        `new` rather than `changed`, because the two send a reader to different
        places -- one to the source's scope, the other to an edit.
        """
        arrived = _plan(
            documents=_documents(INC_4821=SNAPSHOT, INC_4901=SNAPSHOT, INC_5102=SNAPSHOT)
        )

        lines = {line.step.id: line for line in diff(arrived, _plan())}

        assert lines["extract"].status is StepStatus.DOCUMENTS_CHANGED
        assert lines["extract"].moved == ("INC_5102 new",)

    def test_a_raised_converter_version_reruns_the_steps_reading_documents(self):
        """Example 6: the one where `pdf-markdown` went from 1.3.0 to 1.4.0.

        The converted text those steps read is addressed by the converter's
        version (R5.4), so the text moves without any snapshot moving.
        """
        raised = _plan(converters=[CONVERTER.model_copy(update={"version": "1.4.0"})])

        statuses = _statuses(raised, _plan())

        assert statuses["extract"] is StepStatus.CONVERTERS_CHANGED
        assert statuses["verify"] is StepStatus.CONVERTERS_CHANGED
        assert statuses["report"] is StepStatus.UPSTREAM_CHANGED, "reads verify, not documents"

    def test_reordering_two_converters_changes_nothing(self):
        """A converter's position in the list is an installation detail (R5.6)."""
        second = PinnedConverter(
            id="markdown-text", version="1.0.0", media_type="text/markdown", kind="markdown"
        )

        statuses = _statuses(
            _plan(converters=[second, CONVERTER]), _plan(converters=[CONVERTER, second])
        )

        assert set(statuses.values()) == {StepStatus.CACHED}

    def test_what_dossier_itself_says_is_in_no_plan(self):
        """Counter-example (row 7): the one where dossier's retry wrapper was edited.

        Nothing in a resolved plan carries it, because nothing in a key does
        (R0.5 row 5); two plans resolved before and after such an edit are the
        same plan, and every step stays `cached`.
        """
        before, after = _plan(), _plan()

        assert before == after
        assert set(_statuses(after, before).values()) == {StepStatus.CACHED}

    def test_a_manifest_that_pinned_no_converters_is_not_a_change(self):
        """Counter-example (row 10): a run from before converters were recorded.

        Absence is not a different converter. Reading it as one would print
        `converters changed` against every older manifest forever, and a plan
        nobody reads is worse than one that is occasionally silent (R7.3's
        distinction between `null` and absent).
        """
        statuses = _statuses(_plan(), _plan(converters=[]))

        assert set(statuses.values()) == {StepStatus.CACHED}

    def test_a_departed_document_is_not_a_miss(self):
        """Counter-example (row 8): `INC_4901` tombstoned since the last run.

        Strictly less work. Every key that remains is the key it was, so the
        honest answer is `cached` -- and reporting a change would send someone
        looking for an edit that never happened.
        """
        statuses = _statuses(_plan(documents=_documents(INC_4821=SNAPSHOT)), _plan())

        assert set(statuses.values()) == {StepStatus.CACHED}
