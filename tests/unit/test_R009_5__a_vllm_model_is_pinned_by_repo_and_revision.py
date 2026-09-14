"""R9.5 — a model served by vLLM is pinned by its Hugging Face repository and revision.

A repository name alone is whatever `main` points at today, and a stage key
holds the identifier, not the weights (R5.3 row 4). The revision is a commit, so
it does not move. vLLM does not report which revision it loaded, so this pin is
declared rather than verified -- whoever starts vLLM with `--revision` answers
for it matching (spec 009).
"""

from __future__ import annotations

import pytest

from dossier.domain.model_id import check_pinned

# `_fixtures.md` writes it as the display prefix `1c0f8e6b`. A real revision is
# a 40-character commit.
REVISION = "1c0f8e6b" * 5
DIGEST = "7f3c29a1" * 8


class TestAVllmModelIsPinnedByRepoAndRevision:
    """R9.5 — the commit pins a Hugging Face model; the repository name does not."""

    def test_a_repository_at_a_revision_is_accepted(self):
        """Example 1: the one where `Qwen/Qwen2.5-7B-Instruct` is pinned to `1c0f8e6b`."""
        check_pinned(f"hf:Qwen/Qwen2.5-7B-Instruct@{REVISION}")

    def test_a_repository_with_no_revision_is_refused(self):
        """Example 2: the one where the name says which model and not which weights."""
        with pytest.raises(ValueError) as error:
            check_pinned("hf:Qwen/Qwen2.5-7B-Instruct")

        assert "hf:Qwen/Qwen2.5-7B-Instruct" in str(error.value)

    def test_a_branch_is_refused(self):
        """Example 3: the one where `@main` looks like a pin and moves with every push."""
        with pytest.raises(ValueError):
            check_pinned("hf:Qwen/Qwen2.5-7B-Instruct@main")

    def test_an_ollama_id_is_not_this_rules_to_judge(self):
        """Counter-example (row 4): the one where R9.3 pins it, not this rule."""
        check_pinned(f"ollama:qwen2.5:7b@sha256:{DIGEST}")
