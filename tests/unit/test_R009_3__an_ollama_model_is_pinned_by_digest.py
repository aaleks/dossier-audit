"""R9.3 — an Ollama model is pinned only by its digest.

A tag such as `qwen2.5:7b` moves when the model is re-pulled, and a stage key
holds the identifier, not the weights (R5.3 row 4). An identifier naming only a
tag would let one key mean different weights from one month to the next (R0.5).
The digest is what pins it; the tag only names what to ask the server for.
"""

from __future__ import annotations

import pytest

from dossier.domain.model_id import check_pinned

# `_fixtures.md` writes it as the display prefix `7f3c29a1`. A real identifier
# carries all 64 characters, as every hash in dossier does (R0.7).
DIGEST = "7f3c29a1" * 8


class TestAnOllamaModelIsPinnedByDigest:
    """R9.3 — the digest pins an Ollama model; the tag does not."""

    def test_a_tag_with_its_digest_is_accepted(self):
        """Example 1: the one where `qwen2.5:7b` is pinned to `7f3c29a1`."""
        check_pinned(f"ollama:qwen2.5:7b@sha256:{DIGEST}")

    def test_a_tag_without_a_digest_is_refused_naming_it(self):
        """Example 2: the one where `qwen2.5:7b` alone could be other weights next month.

        A tag moves when the model is re-pulled, and nothing in the key would say so.
        """
        with pytest.raises(ValueError) as error:
            check_pinned("ollama:qwen2.5:7b")

        assert "ollama:qwen2.5:7b" in str(error.value)

    def test_latest_with_a_digest_is_accepted(self):
        """Example 3: the one where the tag says it moves and the digest says it does not.

        The digest pins it; the tag only names what to ask the server for.
        """
        check_pinned(f"ollama:qwen2.5:latest@sha256:{DIGEST}")

    def test_an_anthropic_id_is_not_this_rules_to_judge(self):
        """Counter-example (row 4): the one where R0.6 pins it, not this rule."""
        check_pinned("anthropic:claude-sonnet-4-5-20250929")
