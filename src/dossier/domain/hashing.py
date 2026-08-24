"""The one hash, used everywhere (R0.7).

SHA-256 over bytes, rendered as 64 lowercase hex characters. Snapshot content
hashes, prompt and schema file hashes, and every cache key go through here.

The choice is deliberately boring. `hashlib` ships with Python, so there is
nothing to pin and nothing to reproduce at build time; the digest is stable
across versions, platforms and locales, which is what R0.4 and R5.6 require; and
a stored snapshot can be verified with a plain `sha256sum` by someone who does
not have `dossier` installed at all.
"""

from __future__ import annotations

import hashlib
import re

# Hashes are shortened to this many characters in log lines, plan output and the
# examples in `specs/`. It is a reading convenience and never a stored value.
DISPLAY_LENGTH = 8

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def content_hash(payload: bytes) -> str:
    """The SHA-256 of `payload`, as 64 lowercase hex characters."""
    if not isinstance(payload, bytes | bytearray | memoryview):
        # Refusing text rather than encoding it. A caller who passes a str has an
        # encoding in mind that this function cannot know, and guessing UTF-8
        # would make the digest depend on that guess -- which is exactly the
        # cross-machine variation R0.7 exists to rule out.
        raise TypeError(
            f"content_hash takes bytes, not {type(payload).__name__}. "
            "Encode explicitly at the point where the encoding is known."
        )
    return hashlib.sha256(payload).hexdigest()


def is_content_hash(value: str) -> bool:
    """Whether `value` is a full digest in the one form this system stores."""
    return bool(_DIGEST_RE.match(value))


def short(digest: str) -> str:
    """The display prefix of a digest, for a log line or a plan table.

    Rejects anything that is not a full digest. A run id, a shortened hash or an
    uppercase one would all render as something that *looks* like a hash and is
    not, and the place that confusion surfaces is a support conversation about
    two artifacts that were never the same.
    """
    if not is_content_hash(digest):
        raise ValueError(
            f"{digest!r} is not a content hash. Expected 64 lowercase hex characters; "
            "run ids, shortened hashes and uppercase digests are not hashes."
        )
    return digest[:DISPLAY_LENGTH]
