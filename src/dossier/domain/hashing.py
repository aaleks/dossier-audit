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


def normalised_text(text: str) -> str:
    """Text with line endings normalised, the one form a hash is taken over.

    The rule `text_hash` has always applied -- it gets it for free, because
    `read_text` translates newlines on the way in -- named so that a caller
    holding text rather than a path can apply the same one. Two spellings of
    this would be R5's original failure over again, where `pipeline_hash` was
    taken over raw bytes while prompt hashes were taken over decoded text.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_hash(path) -> str:
    """The hash of a text file the workspace supplies -- a prompt, a schema, a config.

    Line endings are normalised before hashing, and that is the whole reason this
    exists as a named function rather than two call sites choosing for
    themselves. `pipeline_hash` was taken over raw bytes while prompt hashes were
    taken over decoded text, so the same `pipeline.yaml` hashed two ways
    depending on whether the checkout used CRLF -- and the workspace is the
    user's own directory, which dossier does not control and which may have no
    `.gitattributes` (R0.4, R5.6).

    The failure that causes is silent rather than wrong: a team with a Windows
    checkout and Linux CI never matches a manifest, so `--plan` reports every
    step as new forever and the cache is paid for and never used.

    Normalising newlines is not normalising content. Trailing whitespace, a
    changed word, a reordered key all still move the hash -- which is what R5.2's
    counter-example asks for.

    Deliberately not used for payloads. A fetched snapshot is hashed exactly as
    received (R1.43, R2.10); translating newlines there would change the content
    hash of every file it touched and make the store lie about what it holds.
    """
    return content_hash(normalised_text(path.read_text(encoding="utf-8")).encode("utf-8"))
