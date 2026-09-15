"""R9.11 — a `.env` file in the working directory supplies only what the
environment leaves unset.

Endpoints and keys are per machine (R9.2, R9.8), and a `.env` file saves
exporting them by hand. `dossier.config` reads it into what that package reads
the environment through; it never writes the process environment. The shell
always wins, because what a person typed for this one command is the most
specific thing they said.
"""

from __future__ import annotations

import os
from pathlib import Path

from dossier.config.endpoints import endpoint_for
from dossier.config.environment import environment

GOOGLE = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENWEBUI = "http://localhost:8080/api"


def _dotenv(directory: Path, text: str) -> None:
    (directory / ".env").write_text(text, encoding="utf-8")


def _gemini_url(environ) -> str:
    return endpoint_for("gemini", default_url=GOOGLE, environ=environ).url


class TestADotenvFileFillsOnlyWhatTheEnvironmentLeavesUnset:
    """R9.11 — `.env` fills gaps in the environment and never overrides it."""

    def test_a_dotenv_value_is_used_when_the_shell_sets_nothing(self, tmp_path: Path):
        """Example 1: the one where `.env` points Gemini at a local OpenWebUI."""
        _dotenv(tmp_path, f"DOSSIER_GEMINI_URL={OPENWEBUI}\n")

        assert _gemini_url(environment(tmp_path, shell={})) == OPENWEBUI

    def test_the_shell_wins_over_the_dotenv_file(self, tmp_path: Path):
        """Example 2: the one where the shell says Google and `.env` says OpenWebUI."""
        _dotenv(tmp_path, f"DOSSIER_GEMINI_URL={OPENWEBUI}\n")

        merged = environment(tmp_path, shell={"DOSSIER_GEMINI_URL": GOOGLE})

        assert _gemini_url(merged) == GOOGLE

    def test_no_dotenv_file_is_not_an_error(self, tmp_path: Path):
        """Example 3: the one with no `.env`, where each provider's default applies."""
        assert _gemini_url(environment(tmp_path, shell={})) == GOOGLE

    def test_only_dossier_variables_are_read_and_the_process_is_untouched(self, tmp_path: Path):
        """Counter-example (row 4): the one where `.env` tries to set `PATH`.

        Ignored. A file dossier reads for its own settings has no business
        steering which programs a shell finds, and dossier never writes the
        process environment at all.
        """
        before = os.environ.get("PATH")
        _dotenv(tmp_path, "PATH=/opt/other/bin\nDOSSIER_GEMINI_URL=" + OPENWEBUI + "\n")

        merged = environment(tmp_path)

        assert merged.get("PATH") == before
        assert os.environ.get("PATH") == before
        assert "DOSSIER_GEMINI_URL" not in os.environ
