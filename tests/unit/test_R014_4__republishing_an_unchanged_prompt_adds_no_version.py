"""R14.4 — publishing a prompt whose hash is already the latest version's sends nothing.

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
from tests.pipelines import write_pipeline

from dossier.domain.pipeline import PipelineConfig, StepConfig

MODEL = "anthropic:claude-sonnet-4-5-20250929"
EXTRACT = "Extract the fields.\n"
VERIFY = "Verify the extraction.\n"
SUMMARISE = b"Summarise the incident.\n"


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


def _write_bytes(directory: Path, extract: bytes) -> None:
    """`extract`'s prompt byte for byte: `write_text` would choose the line endings."""
    (directory / "prompts").mkdir(parents=True, exist_ok=True)
    (directory / "prompts" / "01_extract.md").write_bytes(extract)
    (directory / "prompts" / "02_verify.md").write_bytes(VERIFY.encode("utf-8"))


def _with_summarise() -> PipelineConfig:
    """The pipeline with a third step, `summarise`, added (row 3)."""
    config = _pipeline()
    return config.model_copy(
        update={
            "steps": [
                *config.steps,
                StepConfig(
                    id="summarise",
                    prompt="prompts/03_summarise.md",
                    input="documents",
                    mode="per_file",
                ),
            ]
        }
    )


class TestRepublishingAnUnchangedPromptAddsNoVersion:
    """R14.4 — a prompt whose hash is already the latest version's is not sent."""

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

    def test_the_second_publish_says_it_created_nothing(self, workspace: Path, monkeypatch):
        """Example 1, through `dossier prompts publish`: the line a person reads.

        The standard pipeline's three steps and its judged `root_cause` are four
        prompts, as the example's are.
        """
        from typer.testing import CliRunner

        import dossier.cli.bootstrap as cli
        from dossier.cli.main import app

        registry = FakePromptRegistry()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", "http://localhost:5000")
        monkeypatch.setattr(
            cli, "build_prompt_registry", lambda settings, **_: registry, raising=False
        )
        write_pipeline(
            workspace, steps=["extract", "verify", "report"], modes={"report": "aggregate"}
        )
        monkeypatch.chdir(workspace)
        publish = ["prompts", "publish", "incident-audit"]
        assert CliRunner().invoke(app, publish).exit_code == 0

        again = CliRunner().invoke(app, publish)

        assert again.exit_code == 0, again.output
        assert "0 versions created, 4 unchanged" in again.output.splitlines(), again.output
        assert len(registry.publishes) == 4, "the second publish sent nothing"

    def test_a_step_added_publishes_one_new_prompt(self, tmp_path: Path):
        """Example 3: the one where a new step is a new prompt, and the rest stand."""
        from dossier.application.prompts import publish_prompts

        _write(tmp_path)
        registry = FakePromptRegistry()
        publish_prompts(registry, config=_pipeline(), directory=tmp_path)
        (tmp_path / "prompts" / "03_summarise.md").write_bytes(SUMMARISE)

        again = publish_prompts(registry, config=_with_summarise(), directory=tmp_path)

        assert [(prompt.name, prompt.version, prompt.created) for prompt in again] == [
            ("incident-audit.extract", 1, False),
            ("incident-audit.verify", 1, False),
            ("incident-audit.summarise", 1, True),
        ]
        assert len(registry.publishes) == 3, "one further send, for the new step alone"

    def test_trailing_whitespace_is_a_new_version(self, tmp_path: Path):
        """Example 4, counter-example: the one a person calls harmless.

        The hash moves (R5.2 row 4), and an edit a person thinks harmless cannot
        be told from a real one by anything that reads only the bytes.
        """
        from dossier.application.prompts import publish_prompts

        _write_bytes(tmp_path, EXTRACT.encode("utf-8"))
        registry = FakePromptRegistry()
        publish_prompts(registry, config=_pipeline(), directory=tmp_path)
        _write_bytes(tmp_path, b"Extract the fields.  \n")

        again = publish_prompts(registry, config=_pipeline(), directory=tmp_path)

        assert [prompt.version for prompt in again] == [2, 1]
        assert len(registry.publishes) == 3

    def test_crlf_line_endings_are_not_a_new_version(self, tmp_path: Path):
        """Example 5, counter-example: the one a checkout on Windows makes.

        Line endings are normalised before hashing (R5), so the key did not
        move, and neither does the registry.
        """
        from dossier.application.prompts import publish_prompts

        _write_bytes(tmp_path, b"Extract the fields.\nCite the span.\n")
        registry = FakePromptRegistry()
        publish_prompts(registry, config=_pipeline(), directory=tmp_path)
        _write_bytes(tmp_path, b"Extract the fields.\r\nCite the span.\r\n")

        again = publish_prompts(registry, config=_pipeline(), directory=tmp_path)

        assert [prompt.version for prompt in again] == [1, 1]
        assert [prompt.created for prompt in again] == [False, False]
        assert len(registry.publishes) == 2, "nothing sent the second time"
