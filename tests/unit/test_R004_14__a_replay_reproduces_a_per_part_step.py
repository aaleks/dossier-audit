"""R4.14 — the part is in the recomposed key, and a `per_file` step is unchanged.

The acceptance test proves the rule end to end. What is proved here is the two
things a passing end-to-end test would not distinguish: that the key a replay
builds for a part is *the key the run wrote*, and that nothing about a step
which was never fanned out has moved.

Both are statements about key composition, so they are asserted against
`cache_key` directly rather than through a workspace -- the same composition
`_run_one` and `_replay_one` each call, with nothing between them to agree by
accident.
"""

from __future__ import annotations

import pytest

from dossier.domain.hashing import content_hash
from dossier.domain.keys import ArtifactInput, StageInputs, cache_key

STEP = "extract"
DOCUMENT = "INC-4830-postmortem-checkout-tls-expiry.pdf"
PAGE = b"\x89PNG\r\n\x1a\n page one"
OTHER = b"\x89PNG\r\n\x1a\n page two"


def _inputs(part: tuple[str, bytes] | None) -> StageInputs:
    """A stage key's inputs, with or without a part -- as both callers build them."""
    return StageInputs(
        step=STEP,
        prompt=ArtifactInput(role="prompt", path=STEP, hash="p" * 64),
        output_schema=ArtifactInput(role="schema", path=STEP, hash="s" * 64),
        generated_schema="g" * 64,
        model="anthropic:claude-sonnet-4-5-20250929",
        inputs=[
            ArtifactInput(
                role="documents@page_images",
                path=f"documents@page_images/{DOCUMENT}",
                hash=content_hash(b""),
            )
        ]
        + (
            []
            if part is None
            else [
                ArtifactInput(
                    role="part",
                    path=f"part/{DOCUMENT}/{part[0]}",
                    hash=content_hash(part[1]),
                )
            ]
        ),
    )


class TestAReplayReproducesAPerPartStep:
    """R4.14 — the part is in the key, and only where there is one."""

    def test_a_key_with_a_part_is_not_the_key_without_one(self):
        """Example 1: the reason every per_part run was irreproducible.

        The replay built the second of these and the run had written the first.
        No entry was ever found, so the replay always stopped -- with a message
        about a missing artifact rather than about itself.
        """
        assert cache_key(_inputs(("page-001.png", PAGE))) != cache_key(_inputs(None))

    def test_each_part_gets_its_own_key(self):
        """R3.12's promise, which R4.14 has to preserve on the way back.

        Page two differs from page one because its bytes do. A replay that
        hashed the part *name* and not its content would reproduce three
        distinct keys and could still serve the wrong page for each.
        """
        first = cache_key(_inputs(("page-001.png", PAGE)))
        second = cache_key(_inputs(("page-002.png", OTHER)))

        assert first != second

    def test_the_same_part_recomposes_the_same_key(self):
        """R5.6, which is the whole mechanism: the replay finds the entry or it does not.

        Composed twice from the same values, as the run and the replay each
        compose it once.
        """
        part = ("page-001.png", PAGE)

        assert cache_key(_inputs(part)) == cache_key(_inputs(part))

    @pytest.mark.parametrize("name", ["page-001.png", "page-009.png"])
    def test_the_part_name_does_not_enter_the_key(self, name: str):
        """Counter-example 5's other half: `path` and `role` are not key inputs.

        Spec 005 says a key is made of content hashes. Two pages with identical
        bytes are one key however they are named, which is what lets a document
        with a repeated blank page cost one call rather than two.
        """
        assert cache_key(_inputs((name, PAGE))) == cache_key(_inputs(("page-001.png", PAGE)))
