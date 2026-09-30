"""R0.7 — every hash is SHA-256 over bytes, rendered as 64 lowercase hex characters.

One algorithm for snapshot content hashes, file hashes and cache keys. No
truncation is stored, and no other digest appears anywhere in the system.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import ast
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


class TestARunIdIsFiledUnderATimeItActuallyWas:
    """R0.7 example 4 pins the shape `20260806T142203Z-4f1a`; R0.8 makes it a path.

    Moved out of a private CLI helper by `/quality`, which noted the format rule
    is a pure decision with a spec behind it and was testable only through the
    command line.
    """

    def test_the_shape_is_the_one_the_fixtures_name(self):
        """The one where the id matches `specs/_fixtures.md` exactly."""
        from datetime import UTC, datetime

        from dossier.domain.resolution import run_id

        made = run_id(datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC), "4f1a")

        assert made == "20260806T142203Z-4f1a"

    def test_ids_sort_in_the_order_the_runs_happened(self):
        """The one `latest_manifest` depends on.

        It finds the newest run by taking the last directory name in sorted
        order. Basic ISO 8601 makes that true; almost any friendlier format
        would not.
        """
        from datetime import UTC, datetime

        from dossier.domain.resolution import run_id

        earlier = run_id(datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC), "aaaa")
        later = run_id(datetime(2026, 9, 8, 9, 0, 0, tzinfo=UTC), "0000")

        assert sorted([later, earlier]) == [earlier, later]

    def test_a_naive_timestamp_is_refused(self):
        """The one where `Z` would be a lie.

        `strftime` appends the `Z` literally whatever the tzinfo says, so a naive
        or local time would be filed as if it were UTC -- silently, and only
        visibly wrong once two machines' runs are sorted together.
        """
        from datetime import UTC, datetime, timedelta, timezone

        import pytest

        from dossier.domain.resolution import run_id

        with pytest.raises(ValueError):
            run_id(datetime(2026, 8, 6, 14, 22, 3), "4f1a")
        # Ahead of UTC and behind it: an offset is refused whichever way it points.
        for hours in (2, -5):
            with pytest.raises(ValueError):
                run_id(
                    datetime(2026, 8, 6, 14, 22, 3, tzinfo=timezone(timedelta(hours=hours))),
                    "4f1a",
                )

        assert run_id(datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC), "4f1a")

    def test_the_id_is_a_legal_directory_name(self):
        """The one found the hard way, by a manifest that could not be written.

        A run id is a directory name (R0.8). The extended ISO form's colons are
        illegal on Windows, so `runs/<run_id>/` could not exist there at all.
        """
        from datetime import UTC, datetime

        from dossier.domain.resolution import run_id

        made = run_id(datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC), "4f1a")

        assert not set(made) & set(':<>"|?*') and "/" not in made and "\\" not in made


class TestNoOtherDigestExistsAnywhere:
    """R0.7's headline second sentence — "no other digest appears anywhere".

    Found unchecked by `/quality`. R0.1 walks the tree for network imports; this
    claim, which is just as structural, was proved only by the absence of any
    other digest today. True now, unenforced tomorrow -- and the failure would be
    silent, because a second hash function produces perfectly plausible hex.
    """

    OTHER_DIGESTS = {
        "md5",
        "sha1",
        "sha224",
        "sha384",
        "sha512",
        "blake2b",
        "blake2s",
        "shake_128",
        "shake_256",
        "sha3_256",
        "sha3_512",
    }

    def modules(self) -> list[Path]:
        package = Path(__file__).resolve().parents[2] / "src" / "dossier"
        return sorted(package.rglob("*.py"))

    def test_at_least_one_module_is_scanned(self):
        """A scan over nothing would make the check below vacuous."""
        assert self.modules()

    def test_no_module_calls_another_digest(self):
        """The one where `hashlib.md5(...)` anywhere would be caught.

        Two hash functions in one system means two answers to "is this the same
        content", and the one that is wrong is whichever a reader did not expect.
        """
        offenders: list[str] = []

        for path in self.modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                # `hashlib.md5(...)` and a bare `md5(...)` after a from-import
                # are the same call spelled two ways.
                called = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if called in self.OTHER_DIGESTS:
                    offenders.append(f"{path.name}:{node.lineno}: {called}()")

        assert not offenders, "\n".join(offenders + ["  Every hash is SHA-256 (R0.7)."])

    def test_builtin_hash_is_never_used_for_content(self):
        """The one that catches `hash()`, which is salted per process.

        `PYTHONHASHSEED` randomises it, so a key derived from it would differ on
        every run of the same machine -- the most direct possible violation of
        R0.4 and R5.6, and one that looks like a flaky cache rather than a bug.
        """
        offenders: list[str] = []

        for path in self.modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "hash"
                ):
                    offenders.append(f"{path.name}:{node.lineno}: hash()")

        assert not offenders, "\n".join(
            offenders + ["  `hash()` is salted per process (R0.4, R5.6)."]
        )

    def test_the_detector_detects(self, tmp_path: Path):
        """The counter-example, and the lesson R0.1 taught two days ago.

        A structural check proved only by its negative rows is a check nobody has
        shown to work. This one is handed a violating module and must catch it.
        """
        module = tmp_path / "probe.py"
        module.write_text(
            "import hashlib\n\n\ndef digest(b):\n    return hashlib.md5(b).hexdigest()\n",
            encoding="utf-8",
        )
        tree = ast.parse(module.read_text(encoding="utf-8"))

        found = [
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in self.OTHER_DIGESTS
        ]

        assert found == ["md5"]
