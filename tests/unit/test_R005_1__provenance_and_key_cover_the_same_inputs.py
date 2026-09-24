"""R5.1 — the provenance record and the cache key describe exactly the same inputs.

Every input to a key appears in the record, and every entry in the record is part
of the key. The two are generated from one structure, so they cannot drift.

Drift here is the worst failure the cache has, because it is invisible from both
sides. A record naming an input the key ignores says a run depended on something
it did not, so a change to that input silently serves a stale artifact. A key
covering an input the record omits produces a cache miss nobody can explain from
the record. Neither shows up as an error.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import pytest

from dossier.domain.keys import (
    PROVENANCE_ONLY,
    ArtifactInput,
    StageInputs,
    cache_key,
    provenance,
)

CONVERTED = ArtifactInput(role="documents", path="converted/INC-4821.md", hash="5d3ba0f7" * 8)
EXTRACTED = ArtifactInput(role="extract", path="extract/INC-4821.json", hash="77c1b40a" * 8)
PROMPT = ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8)
SCHEMA = ArtifactInput(role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8)

MODEL = "anthropic:claude-sonnet-4-5-20250929"
RUN_ID = "20260806T142203Z-4f1a"


def verify_stage(**overrides) -> StageInputs:
    """The `verify` artifact for `INC-4821`, as spec 005's provenance example."""
    fields = {
        "step": "verify",
        "prompt": PROMPT,
        "output_schema": SCHEMA,
        "model": MODEL,
        "inputs": [CONVERTED, EXTRACTED],
    }
    return StageInputs(**{**fields, **overrides})


class TestProvenanceAndKeyAgree:
    """R5.1 — one structure produces both, so they cannot disagree."""

    def test_the_record_names_every_hash_the_key_covers(self):
        """Example 1: the one from spec 005's own provenance example."""
        inputs = verify_stage()

        record = provenance(inputs, run_id=RUN_ID, dossier_version="0.1.0")
        serialised = repr(record)

        for artifact in (CONVERTED, EXTRACTED, PROMPT, SCHEMA):
            assert artifact.hash in serialised
        assert MODEL in serialised

    def test_perturbing_any_single_entry_changes_the_key(self):
        """Example 2: the one that proves every entry is load-bearing.

        Each is changed on its own. An entry that could be altered without moving
        the key is an entry the record claims matters and the cache ignores.
        """
        baseline = cache_key(verify_stage())

        moved = [
            verify_stage(model="anthropic:claude-opus-4-1-20250805"),
            verify_stage(prompt=PROMPT.model_copy(update={"hash": "a3f9c1e2" * 8})),
            verify_stage(output_schema=SCHEMA.model_copy(update={"hash": "a3f9c1e2" * 8})),
            verify_stage(inputs=[CONVERTED]),
            verify_stage(options={"temperature": "0"}),
        ]

        for inputs in moved:
            assert cache_key(inputs) != baseline

    def test_the_record_holds_nothing_beyond_the_key_but_the_named_exceptions(self):
        """Example 3: the one that catches an input recorded but not keyed.

        The permitted extras are a named, closed set rather than a convention.
        Anything else appearing in the record is an input the cache does not know
        about, which is exactly the drift this rule forbids.
        """
        inputs = verify_stage()

        record = provenance(inputs, run_id=RUN_ID, dossier_version="0.1.0")
        keyed = set(inputs.keyed())

        assert set(record) - keyed <= PROVENANCE_ONLY, (
            "a field in the record that is neither keyed nor a named exception is "
            "an input the cache does not know about"
        )
        assert keyed <= set(record), "every keyed input must be visible in the record"

    def test_the_provenance_only_fields_do_not_reach_the_key(self):
        """Counter-example (row 4): the one where two fields are deliberately excluded.

        `run_id` and `dossier_version` are recorded so a person can trace an
        artifact, and excluded from the key because neither may change an output
        (R0.4). If they reached the key, every run would miss the cache entirely.
        """
        first = provenance(verify_stage(), run_id=RUN_ID, dossier_version="0.1.0")
        second = provenance(
            verify_stage(), run_id="2026-09-08T10:00:00Z-aaaa", dossier_version="9.9.9"
        )

        assert first["run_id"] != second["run_id"]
        assert first["dossier_version"] != second["dossier_version"]
        assert first["cache_key"] == second["cache_key"]

    def test_the_step_id_is_recorded_and_not_keyed(self):
        """The one that follows spec 005's formula rather than intuition.

        `K_stage` is composed of the prompt, schema, model, options and input
        hashes -- the step id is not in it. Two steps with identical inputs are
        the same computation and correctly share a cache entry; the id is in the
        record so a reader can still see which step wrote the artifact.
        """
        assert cache_key(verify_stage(step="verify")) == cache_key(verify_stage(step="report"))
        assert provenance(verify_stage(), run_id=RUN_ID, dossier_version="0.1.0")["step"] == (
            "verify"
        )

    def test_a_key_is_a_full_length_lowercase_sha256(self):
        """The one where the key is the project's hash, not a shortened display form.

        R0.7 fixes the shape. The eight-character forms in the specs are a reading
        convention, and writing one into a cache path would collide far sooner
        than anyone would expect.
        """
        key = cache_key(verify_stage())

        assert len(key) == 64
        assert key == key.lower()
        assert set(key) <= set("0123456789abcdef")


class TestTheStructureRefusesToDrift:
    """R5.1 example 3 — rejected at construction, not discovered later."""

    def test_an_unknown_field_is_refused(self):
        """The one where a new input is added without thinking about the key.

        Adding a field to the record is how the two drift. Pydantic's
        `extra=forbid` makes it impossible rather than merely discouraged.
        """
        with pytest.raises(ValueError):
            StageInputs(
                step="verify",
                prompt=PROMPT,
                output_schema=SCHEMA,
                model=MODEL,
                inputs=[CONVERTED],
                endpoint="https://eu.example.invalid",
            )

    def test_the_attempt_count_is_recorded_and_never_keyed(self):
        """Counter-example (row 5): the one written on the second try.

        `attempts` is in the record, so a person can see it took two goes
        (R6.2 row 1), and out of the key: a retried answer that validated is
        the same answer, and an artifact is never re-derived because the road
        to it was longer.
        """
        inputs = verify_stage()

        first = provenance(inputs, run_id=RUN_ID, dossier_version="0.1.0", attempts=1)
        second = provenance(inputs, run_id=RUN_ID, dossier_version="0.1.0", attempts=2)

        assert second["attempts"] == 2
        # Every named exception but `tokens`, which only a stage that knows what
        # its calls cost writes, and this record was built without (R5.11).
        assert set(second) - set(inputs.keyed()) == PROVENANCE_ONLY - {"tokens"}
        assert first["cache_key"] == second["cache_key"] == cache_key(inputs)
