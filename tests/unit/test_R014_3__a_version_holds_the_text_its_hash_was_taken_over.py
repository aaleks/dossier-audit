"""R14.3 — a version holds the text the prompt's hash was taken over, tagged with that hash.

The tie between a version in MLflow and a key in a provenance record. Without
it a person has a prompt they can read and no way to know which run rendered it,
which would make publishing a filing exercise rather than an answer to "what
changed between these two runs".

`dossier.prompt_hash` is asserted against `text_hash` -- spec 005's own function,
the one whose output goes into the stage key -- rather than against a digest
recomputed here. A tag that merely looked like a hash would pass the second and
fail the only thing the rule claims.
"""

from __future__ import annotations

from pathlib import Path

from dossier.domain.hashing import is_content_hash, text_hash
from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"
VERIFY = "Verify the extraction against the source document.\n"


def _pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model=MODEL,
        steps=[
            StepConfig(
                id="verify", prompt="prompts/02_verify.md", input="documents", mode="per_file"
            )
        ],
    )


class TestAVersionHoldsTheTextItsHashWasTakenOver:
    """R14.3 — a version holds the text its hash was taken over, tagged with that hash."""

    def test_a_prompt_carries_the_four_tags_that_tie_it_to_a_provenance_record(
        self, tmp_path: Path
    ):
        """The one where a person in MLflow can get back to the run that rendered it.

        The hash is the whole tie, and it is the same value `text_hash` puts into
        the stage key -- written here by hashing the file on disk, so the
        assertion would fail if the projection ever hashed something else. All 64
        characters (R0.7): eight would read as a hash and collide differently.
        """
        from dossier.domain.prompts import publish_set

        on_disk = tmp_path / "02_verify.md"
        on_disk.write_text(VERIFY, encoding="utf-8")

        published = publish_set(_pipeline(), {"prompts/02_verify.md": VERIFY})

        assert len(published) == 1
        assert published[0].tags == {
            "dossier.prompt_hash": text_hash(on_disk),
            "dossier.pipeline": "incident-audit",
            "dossier.step": "verify",
            "dossier.path": "prompts/02_verify.md",
        }
        assert is_content_hash(published[0].tags["dossier.prompt_hash"])

    def test_a_crlf_rewrite_changes_neither_the_template_nor_its_hash(self):
        """Row 1's other half, and what R14.4 row 5 rests on.

        A workspace is the user's own directory, which dossier does not control
        and which may have no `.gitattributes`. Publishing the bytes as handed
        over would show a person a version differing from the one their
        colleague published from the same commit on the other operating system,
        while the key both runs computed was identical (R5, "How a text file is
        hashed").

        The third assertion is the guard. Normalising newlines is not
        normalising content: a green that stripped or collapsed whitespace would
        satisfy the first two and quietly make a real edit invisible, which is
        what R14.4 row 4 refuses.
        """
        from dossier.domain.prompts import publish_set

        def published(text: str):
            return publish_set(_pipeline(), {"prompts/02_verify.md": text})[0]

        unix = published(VERIFY)
        windows = published(VERIFY.replace("\n", "\r\n"))
        spaced = published(VERIFY.replace("\n", " \n", 1))

        assert windows.template == unix.template
        assert windows.tags["dossier.prompt_hash"] == unix.tags["dossier.prompt_hash"]
        assert spaced.tags["dossier.prompt_hash"] != unix.tags["dossier.prompt_hash"], (
            "trailing whitespace is a real edit and must still move the hash"
        )
