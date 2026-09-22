"""R14.1 — publishing sends every prompt the pipeline names, and reports what came back.

The use case above the projection. `publish_set` decides what a publish *would*
send; this reads the files off disk, hands them over, and calls the registry --
which is given rather than built, because which registry this is belongs to the
composition root and not to a use case (spec 012's shape).

The registry counts. R14.1 is a claim about how many prompts exist afterwards,
and a fake that only returned a version number could not prove it.
"""

from __future__ import annotations

from pathlib import Path

from tests.fakes import FakePromptRegistry

from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"
EXTRACT = "Extract the fields.\n"
VERIFY = "Verify the extraction.\n"
RUBRIC = "Is the stated root cause supported by the named document?\n"


def _pipeline() -> PipelineConfig:
    return PipelineConfig(
        name="incident-audit",
        sources=["incidents-jira"],
        model=MODEL,
        steps=[
            StepConfig(
                id="extract",
                prompt="prompts/01_extract.md",
                input="documents",
                mode="per_file",
                output="schemas/incident.yaml",
            ),
            StepConfig(
                id="verify",
                prompt="prompts/02_verify.md",
                input="documents",
                mode="per_file",
                output="schemas/incident.yaml",
            ),
        ],
    )


def _write(directory: Path) -> None:
    """The pipeline's own directory, as a workspace holds it."""
    (directory / "prompts").mkdir(parents=True)
    (directory / "rubrics").mkdir(parents=True)
    (directory / "prompts" / "01_extract.md").write_text(EXTRACT, encoding="utf-8")
    (directory / "prompts" / "02_verify.md").write_text(VERIFY, encoding="utf-8")
    (directory / "rubrics" / "root_cause.md").write_text(RUBRIC, encoding="utf-8")


class TestPublishingSendsEveryPromptThePipelineNames:
    """R14.1 — every step of a pipeline publishes as one prompt named `<pipeline>.<step id>`."""

    def test_every_prompt_the_pipeline_names_is_sent_and_reported(self, tmp_path: Path):
        """The one where the files on disk reach the registry under their own names.

        Three sent, not two: the rubric `root_cause` is judged against counts as
        a prompt (R14.2), and both steps declaring it publish it once. What comes
        back carries the version, which is the only thing a person needs to find
        the entry in MLflow.
        """
        from dossier.application.prompts import publish_prompts

        _write(tmp_path)
        registry = FakePromptRegistry()
        declared = {"root_cause": "rubrics/root_cause.md"}

        published = publish_prompts(
            registry,
            config=_pipeline(),
            directory=tmp_path,
            rubrics={"extract": declared, "verify": declared},
        )

        assert [sent["name"] for sent in registry.publishes] == [
            "incident-audit.extract",
            "incident-audit.verify",
            "incident-audit.judge.root_cause",
        ]
        assert [sent["template"] for sent in registry.publishes] == [EXTRACT, VERIFY, RUBRIC]
        assert [prompt.version for prompt in published] == [1, 1, 1]
        assert [prompt.name for prompt in published] == [
            sent["name"] for sent in registry.publishes
        ]
