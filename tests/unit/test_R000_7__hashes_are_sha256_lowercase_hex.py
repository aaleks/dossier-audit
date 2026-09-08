"""R0.7 — every hash is SHA-256 over bytes, rendered as 64 lowercase hex characters.

One algorithm for snapshot content hashes, file hashes and cache keys. No
truncation is stored, and no other digest appears anywhere in the system.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from dossier.domain.hashing import DISPLAY_LENGTH, content_hash, is_content_hash, short

HEX64 = re.compile(r"^[0-9a-f]{64}$")

RUN_ID = "20260806T142203Z-4f1a"


class TestContentHash:
    """R0.7 — one algorithm, everywhere."""

    def test_a_snapshot_can_be_verified_without_dossier_installed(self, workspace: Path):
        """The one where the digest matches a plain sha256sum.

        Example 1. This is the whole reason the algorithm is boring: someone
        holding a snapshot and no tooling can still check it is what it claims.
        """
        payload = (workspace / "inbox" / "incidents" / "INC-4821.md").read_bytes()

        assert content_hash(payload) == hashlib.sha256(payload).hexdigest()

    def test_the_stored_form_is_64_lowercase_hex_characters(self, workspace: Path):
        """The one where the full digest is what gets written down."""
        payload = (workspace / "inbox" / "incidents" / "INC-4821.md").read_bytes()

        digest = content_hash(payload)

        assert len(digest) == 64
        assert HEX64.match(digest), f"{digest!r} is not 64 lowercase hex characters"

    def test_hashing_is_over_bytes_not_text(self):
        """The one where a str is refused rather than quietly encoded.

        Example 2 in the rule is "identical across Windows and Linux". Asserting
        that two identical byte strings hash the same is trivially true and
        proves nothing; the way that claim actually breaks is a caller passing
        text and the encoding being chosen for them. So refuse text.
        """
        with pytest.raises(TypeError):
            content_hash("total exposure CHF 48'200")  # type: ignore[arg-type]

    def test_an_empty_payload_still_hashes(self):
        """The one where a zero-byte file is a real document (R1.2 example 3)."""
        assert content_hash(b"") == hashlib.sha256(b"").hexdigest()
        assert HEX64.match(content_hash(b""))

    def test_one_byte_of_difference_changes_the_digest(self):
        """The one where a trailing space is a real edit for a folder source.

        R2.10 example 2 leans on this directly.
        """
        assert content_hash(b"incident\n") != content_hash(b"incident \n")


class TestDisplayPrefix:
    """R0.7 — shortening is for reading, never for storing."""

    def test_a_short_hash_is_a_prefix_of_the_stored_one(self):
        """The one where `a3f9c1e2` in a log line is the same hash."""
        digest = content_hash(b"incident")

        assert short(digest) == digest[:DISPLAY_LENGTH]
        assert len(short(digest)) == 8

    def test_shortening_never_changes_what_is_stored(self):
        """Example 3: the stored value is never truncated."""
        digest = content_hash(b"incident")

        short(digest)

        assert len(content_hash(b"incident")) == 64
        assert content_hash(b"incident") == digest

    def test_a_run_id_is_not_a_hash(self):
        """Counter-example (row 4): the one where a timestamp is not a digest.

        A run id looks identifier-shaped and is deliberately excluded from every
        cache key (R0.4). Shortening one would render something that reads like
        a hash in a log line and is not, which is the confusion worth refusing.
        """
        assert not is_content_hash(RUN_ID)

        with pytest.raises(ValueError):
            short(RUN_ID)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("A3F9C1E2" * 8, id="uppercase"),
            pytest.param("a3f9c1e2", id="already-shortened"),
            pytest.param("", id="empty"),
            pytest.param("g" * 64, id="not-hex"),
        ],
    )
    def test_only_a_full_lowercase_digest_counts_as_a_hash(self, value: str):
        """The one where a near-miss is rejected rather than passed along."""
        assert not is_content_hash(value)
