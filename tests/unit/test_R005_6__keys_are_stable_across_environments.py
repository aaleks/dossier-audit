"""R5.6 — key computation is stable across machines, processes and Python versions.

No `hash()`, no dict or set iteration order, no absolute paths, no locale, no
timezone. This is the rule the whole spec rests on, and every one of those five
has broken a cache in some project before.

Three of the rows below run real subprocesses. They have to: `PYTHONHASHSEED`,
`LC_ALL` and `TZ` are all read at interpreter start, so setting them inside this
process would prove nothing at all.

The rows below are the rule's example table, transcribed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from dossier.domain.keys import ArtifactInput, StageInputs, cache_key

PROMPT = ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8)
SCHEMA = ArtifactInput(role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8)
CONVERTED = ArtifactInput(role="documents", path="converted/INC-4821.md", hash="5d3ba0f7" * 8)
EXTRACTED = ArtifactInput(role="extract", path="extract/INC-4821.json", hash="77c1b40a" * 8)

PROBE = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {src!r})
    from dossier.domain.keys import ArtifactInput, StageInputs, cache_key

    sys.stdout.write(cache_key(StageInputs(
        step="verify",
        prompt=ArtifactInput(role="prompt", path="prompts/02_verify.md", hash="0e52dd18" * 8),
        output_schema=ArtifactInput(
            role="schema", path="schemas/incident.json", hash="b81f0c6d" * 8
        ),
        model="anthropic:claude-sonnet-4-5-20250929",
        options={{"temperature": "0", "max_tokens": "4096"}},
        inputs=[
            ArtifactInput(role="documents", path="converted/INC-4821.md",
                          hash="5d3ba0f7" * 8),
            ArtifactInput(role="extract", path="extract/INC-4821.json",
                          hash="77c1b40a" * 8),
        ],
    )))
    """
)


def probe(
    repo_root: Path, *, env: dict[str, str] | None = None, cwd: Path | None = None
) -> str:
    """Compute the `verify` key in a fresh interpreter and return it."""
    return subprocess.run(
        [sys.executable, "-c", PROBE.format(src=str(repo_root / "src"))],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(cwd or repo_root),
    ).stdout


def verify(**overrides) -> StageInputs:
    fields = {
        "step": "verify",
        "prompt": PROMPT,
        "output_schema": SCHEMA,
        "model": "anthropic:claude-sonnet-4-5-20250929",
        "options": {"temperature": "0", "max_tokens": "4096"},
        "inputs": [CONVERTED, EXTRACTED],
    }
    return StageInputs(**{**fields, **overrides})


class TestKeysAreStableAcrossEnvironments:
    """R5.6 — the same inputs, the same key, anywhere."""

    def test_two_processes_with_different_hash_seeds_agree(self, repo_root: Path):
        """Example 1: the one where a set or a `hash()` would leak.

        `options` and `inputs` are the two places a set could plausibly be used.
        Under a different seed either would reorder, and the two keys would part.
        """
        keys = [
            probe(repo_root, env={"PYTHONHASHSEED": seed, "PATH": ""})
            for seed in ("0", "987654")
        ]

        assert keys[0] == keys[1]

    def test_the_working_directory_does_not_reach_the_key(
        self, repo_root: Path, tmp_path: Path
    ):
        """Example 2: the one run from two different directories.

        Nothing path-shaped enters a key at all -- only hashes, identifiers and
        declared options -- so there is no absolute path to normalise. This is
        the assertion that keeps it that way.
        """
        assert probe(repo_root, cwd=repo_root) == probe(repo_root, cwd=tmp_path)

    def test_locale_and_timezone_do_not_reach_the_key(self, repo_root: Path):
        """Example 3: the one under Turkish casing and Tokyo time.

        `tr_TR` is the locale that breaks naive lowercasing -- dotted and
        dotless i -- and it is the reason a key must never be taken over
        locale-cased text. `Asia/Tokyo` catches any date formatted on the way in.
        """
        import os

        base = {**os.environ, "PYTHONHASHSEED": "0"}
        turkish = probe(repo_root, env={**base, "LC_ALL": "tr_TR.UTF-8", "TZ": "Asia/Tokyo"})
        plain = probe(repo_root, env={**base, "LC_ALL": "C", "TZ": "UTC"})

        assert turkish == plain

    def test_inputs_supplied_in_a_different_order_produce_the_same_key(self):
        """Counter-example (row 4): the one where order is deliberately not information.

        Two inputs given in the other order are the same two inputs. Sorting
        before hashing is what makes that true; without it a stage whose inputs
        arrived from a differently-ordered query would miss its own cache entry.
        """
        assert cache_key(verify(inputs=[CONVERTED, EXTRACTED])) == cache_key(
            verify(inputs=[EXTRACTED, CONVERTED])
        )

    def test_options_written_in_a_different_order_produce_the_same_key(self):
        """The same claim for the options mapping.

        A dict preserves insertion order, so two pipelines declaring the same
        options in a different order would otherwise key differently.
        """
        assert cache_key(verify(options={"temperature": "0", "max_tokens": "4096"})) == (
            cache_key(verify(options={"max_tokens": "4096", "temperature": "0"}))
        )

    def test_a_different_input_still_changes_the_key(self):
        """The one where stability is not sameness.

        A key that never moved would be perfectly stable and perfectly useless.
        """
        other = CONVERTED.model_copy(update={"hash": "c4a70b93" * 8})

        assert cache_key(verify(inputs=[other, EXTRACTED])) != cache_key(verify())


class TestTextFilesAreHashedOneWay:
    """R5.6 — a text file read from the workspace hashes the same on every machine.

    Found by `/quality`: `pipeline_hash` was taken over `read_bytes` and prompt
    hashes over `read_text`, which performs universal-newline translation. Two
    conventions for the same class of file, and the safer one applied to the file
    that needed it less.

    The consequence is a silent cost rather than a wrong answer. A team with a
    Windows checkout and Linux CI has the same `pipeline.yaml` hashing two ways,
    so no manifest ever matches and `--plan` reports everything as new forever.
    The workspace is `Path.cwd()` -- a directory dossier does not control and
    which may have no `.gitattributes` to save it.
    """

    def test_a_config_file_hashes_the_same_whatever_its_line_endings(self, tmp_path: Path):
        """The one where the same file arrives from two checkouts."""
        from dossier.domain.hashing import text_hash

        crlf = tmp_path / "crlf.yaml"
        lf = tmp_path / "lf.yaml"
        crlf.write_bytes(b"sources: [incidents-manual]\r\nmodel: x\r\n")
        lf.write_bytes(b"sources: [incidents-manual]\nmodel: x\n")

        assert text_hash(crlf) == text_hash(lf)

    def test_a_real_edit_still_changes_the_hash(self, tmp_path: Path):
        """The counter-example: normalising line endings is not normalising content.

        R5.2's row 4 is the claim that matters here -- a "harmless" edit is not
        distinguishable from a real one -- and trailing whitespace survives
        newline translation, so it still moves the key.
        """
        from dossier.domain.hashing import text_hash

        plain = tmp_path / "plain.md"
        trailing = tmp_path / "trailing.md"
        plain.write_bytes(b"{{documents}}\n")
        trailing.write_bytes(b"{{documents}} \n")

        assert text_hash(plain) != text_hash(trailing)

    def test_a_snapshot_payload_is_still_hashed_byte_for_byte(self):
        """The boundary: content is not config.

        A fetched payload is hashed exactly as received (R1.2, R2.10). Newline
        translation there would change the content hash of every file it touched
        and make the store lie about what it holds.
        """
        from dossier.domain.hashing import content_hash

        assert content_hash(b"a\r\nb\r\n") != content_hash(b"a\nb\n")
