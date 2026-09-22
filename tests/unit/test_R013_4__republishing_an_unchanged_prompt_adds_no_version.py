"""R13.4 — publishing a prompt whose hash is already the latest version's sends nothing.

The rule that keeps a version history readable. `register_prompt` creates a
version every time it is called, including for text identical to the version
above it, so a publish that did not ask first would leave a person comparing a
`v1` and a `v2` that differ in nothing.

The registry counts sends, not just versions: "nothing was written" is the claim,
and a fake that only reported the resulting version number could not tell a
skipped publish from one that wrote the same thing again.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakePromptRegistry

from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"
EXTRACT = "Extract the fields.\n"
VERIFY = "Verify the extraction.\n"


def _pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract", prompt="prompts/01_extract.md", input="documents", mode="per_file"
            ),
            StepConfig(
                id="verify", prompt="prompts/02_verify.md", input="documents", mode="per_file"
            ),
        ],
    )


def _write(directory: Path, verify: str = VERIFY) -> None:
    (directory / "prompts").mkdir(parents=True, exist_ok=True)
    (directory / "prompts" / "01_extract.md").write_text(EXTRACT, encoding="utf-8")
    (directory / "prompts" / "02_verify.md").write_text(verify, encoding="utf-8")


class TestRepublishingAnUnchangedPromptAddsNoVersion:
    """R13.4 — a prompt whose hash is already the latest version's is not sent."""

    def test_publishing_twice_with_nothing_edited_sends_nothing_the_second_time(
        self, tmp_path: Path
    ):
        """Example 1: the one a person can run twice without thinking about it.

        Two prompts, each still at version 1, and zero sends the second time.
        Counting the sends rather than the versions is the point: a publish that
        merged the same text again would leave both at v2, and a person opening
        the registry would find two entries to compare that differ in nothing.
        """
        from dossier.application.prompts import publish_prompts

        _write(tmp_path)
        registry = FakePromptRegistry()

        publish_prompts(registry, config=_pipeline(), directory=tmp_path)
        sent_first = len(registry.publishes)
        again = publish_prompts(registry, config=_pipeline(), directory=tmp_path)

        assert sent_first == 2
        assert len(registry.publishes) == 2, "the second publish sent nothing"
        assert [prompt.version for prompt in again] == [1, 1]
        assert [prompt.created for prompt in again] == [False, False]

    def test_only_the_edited_prompt_gets_a_version(self, tmp_path: Path):
        """Example 2: the one where a key cascades downstream and a prompt does not.

        Editing `verify` changes `verify`'s key and every key after it (R5.2),
        and changes no other prompt's text. So `verify` reaches version 2 and
        `extract` stays at version 1 -- a registry that versioned the cascade
        would claim an edit nobody made.
        """
        from dossier.application.prompts import publish_prompts

        _write(tmp_path)
        registry = FakePromptRegistry()
        publish_prompts(registry, config=_pipeline(), directory=tmp_path)

        _write(tmp_path, verify="Verify the extraction, and say where you looked.\n")
        again = publish_prompts(registry, config=_pipeline(), directory=tmp_path)

        assert [prompt.version for prompt in again] == [1, 2]
        assert [prompt.created for prompt in again] == [False, True]
        assert len(registry.publishes) == 3, "one further send, for the edited prompt alone"
