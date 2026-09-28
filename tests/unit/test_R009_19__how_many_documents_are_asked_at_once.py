"""R9.19 — `dossier run` asks a model about at most `N` of a step's documents at
once, and nothing it writes depends on `N`.

How `N` is decided, without a run: `concurrency` reads the flag, else the
environment `.env` fills, else 1, and refuses anything that is not a whole
number of at least 1 by naming where it came from. A decision, so it is in
`domain/` with the environment handed in (CLAUDE.md, "Default to domain/").

What a step does with `N`, without the CLI: `execute` is run directly over three
of the scoring example's incidents, with a model whose calls pass through a
`Gate` that counts how many were in flight together.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from tests.fakes import Gate
from tests.pipelines import prompt_for
from tests.scoring_example import ISSUES

from dossier.application.run import RunInputs, execute
from dossier.domain.concurrency import concurrency
from dossier.domain.fields import OutputSchema
from dossier.domain.pipeline import PipelineConfig, StepConfig
from dossier.infrastructure.models._http import ModelRequestFailed
from dossier.infrastructure.models.ollama import ollama
from dossier.infrastructure.models.openai_compatible import hf

MODEL = "anthropic:claude-sonnet-4-5-20250929"
SNAPSHOTS = {
    "INC-4821": "a3f9c1e2" * 8,
    "INC-4822": "77c1b40a" * 8,
    "INC-4901": "0e52dd18" * 8,
}
CONFIG = PipelineConfig(
    name="incident-audit",
    sources=["incidents-jira"],
    model=MODEL,
    steps=[
        StepConfig(
            id="extract",
            prompt="prompts/extract.md",
            input="documents",
            mode="per_file",
            output="schemas/incident.yaml",
        )
    ],
)


class GatedModel:
    """A model client whose every call passes through `gate`.

    It answers for any document by abstaining (R6.5), or, `refusing`, raises
    what a client raises when the endpoint still refuses after R9.17's
    retries -- naming the document, so which one stopped the run can be read.
    """

    model_id = MODEL

    def __init__(self, gate: Gate, *, refusing: bool = False) -> None:
        self.gate = gate
        self.refusing = refusing

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        document = re.search(r'<document key="([^"]+)">', prompt).group(1)
        self.gate.through(document)
        if self.refusing:
            raise ModelRequestFailed(
                f"POST https://api.anthropic.com/v1/messages refused {document}"
            )
        return json.dumps(
            {
                "document": document,
                "fields": [
                    {"field": "loss_amount", "value": None, "reason": "not stated in document"}
                ],
            }
        )


def _run(workspace: Path, model: GatedModel, **options):
    """One run of `extract` over the three incidents; its report."""
    from dossier.infrastructure.cache import ArtifactCache

    return execute(
        RunInputs(
            pipeline=CONFIG,
            pipeline_hash="6e0d4b27" * 8,
            documents=SNAPSHOTS,
            document_text=ISSUES,
            schemas={
                "extract": OutputSchema(
                    schema={"type": "object"}, declaration_hash="d24c86e1" * 8
                )
            },
            prompts={"extract": prompt_for(["documents"])},
        ),
        workspace=workspace,
        model=model,
        cache=ArtifactCache(workspace, namespace="stage"),
        run_id="20260806T142203Z-4f1a",
        started_at=datetime(2026, 8, 6, 14, 22, 3, tzinfo=UTC),
        dossier_version="0.1.0",
        **options,
    )


class TestHowManyDocumentsAreAskedAtOnce:
    """R9.19 — where `N` comes from, and what is refused."""

    def test_the_flag_says_how_many(self):
        """Row 1: the one with `--concurrency 3`."""
        assert concurrency({}, flag="3") == 3

    def test_the_machine_says_how_many(self):
        """Row 3: the one with `DOSSIER_CONCURRENCY=2` and no flag."""
        assert concurrency({"DOSSIER_CONCURRENCY": "2"}) == 2

    def test_the_command_line_wins_over_the_machine(self):
        """Row 4: the one with both: what is said on the command line wins."""
        assert concurrency({"DOSSIER_CONCURRENCY": "2"}, flag="3") == 3

    def test_unset_is_one(self):
        """Row 5: the one with neither set."""
        assert concurrency({}) == 1

    def test_set_and_empty_is_unset(self):
        """Row 5's boundary: `.env.example` ships the variable blank."""
        assert concurrency({"DOSSIER_CONCURRENCY": ""}) == 1

    @pytest.mark.parametrize("value", ["0", "-1", "four", "2.5", " 3", "+3", "", "٣"])
    def test_a_flag_that_is_not_a_count_is_refused_by_name(self, value: str):
        """Row 7, a counter-example: a flag given, and not a whole number of at least 1.

        An empty flag is a value someone typed, not an unset one. A digit
        from another script is a digit to `str.isdigit` and not to a person
        reading `ps`, so it is refused rather than read as 3.
        """
        with pytest.raises(ValueError) as refused:
            concurrency({}, flag=value)

        assert str(refused.value) == (
            f"--concurrency is {value!r}; it takes a whole number of at least 1."
        )

    @pytest.mark.parametrize("value", ["0", "2.5", "many"])
    def test_a_setting_that_is_not_a_count_is_refused_by_name(self, value: str):
        """Row 7, a counter-example: the one in `.env`, named as the variable."""
        with pytest.raises(ValueError) as refused:
            concurrency({"DOSSIER_CONCURRENCY": value})

        assert str(refused.value) == (
            f"DOSSIER_CONCURRENCY is {value!r}; it takes a whole number of at least 1."
        )

    def test_a_refused_setting_is_refused_even_under_a_flag(self):
        """Row 7's boundary: the flag wins, so a setting it overrides is not read."""
        assert concurrency({"DOSSIER_CONCURRENCY": "many"}, flag="2") == 2

    def test_a_large_count_is_not_capped(self):
        """No ceiling: `dossier` does not know a provider's limit."""
        assert concurrency({}, flag="64") == 64


class TestAStepAsksAtMostNAtOnce:
    """R9.19 — what `execute` does with `N`."""

    def test_three_at_once(self, tmp_path: Path):
        """Row 1: the one where all three are asked before any is answered."""
        gate = Gate(expected=3, meet=3)

        report = _run(tmp_path, GatedModel(gate), concurrency=3)

        assert gate.most_at_once == 3
        assert [result.document for result in report.steps[0].results] == sorted(SNAPSHOTS)
        assert not report.failed

    def test_results_are_in_document_order_whatever_order_they_were_answered_in(
        self, tmp_path: Path
    ):
        """Row 2: the one answered last-first."""
        gate = Gate(expected=3, meet=3, order=sorted(SNAPSHOTS, reverse=True))

        report = _run(tmp_path, GatedModel(gate), concurrency=3)

        assert gate.most_at_once == 3
        assert [result.document for result in report.steps[0].results] == sorted(SNAPSHOTS)

    def test_one_at_a_time_unless_told(self, tmp_path: Path):
        """Row 5: the one where no concurrency is given."""
        gate = Gate(expected=3, meet=1)

        _run(tmp_path, GatedModel(gate))

        assert gate.most_at_once == 1
        assert gate.asked == sorted(SNAPSHOTS)

    def test_a_refused_request_starts_nothing_more(self, tmp_path: Path):
        """Row 6: the one where every request is refused, two at a time."""
        gate = Gate(expected=3, meet=2)

        with pytest.raises(ModelRequestFailed, match="refused INC-4821$"):
            _run(tmp_path, GatedModel(gate, refusing=True), concurrency=2)

        assert sorted(gate.asked) == ["INC-4821", "INC-4822"]


def _at_once(count: int, call) -> None:
    """`call` from `count` threads released together, as a run's workers are."""
    start = threading.Barrier(count)
    failures: list[BaseException] = []

    def worker() -> None:
        start.wait(timeout=5)
        try:
            call()
        except BaseException as error:  # pragma: no cover - reported below
            failures.append(error)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not failures, failures


class _SlowServer:
    """A model server whose listing takes a while, counting what it is asked.

    Slow so that three callers arriving together all arrive while the first is
    still asking what is served: a check made once per caller would be seen.
    """

    def __init__(self, listing: str, listed: dict, answer: dict) -> None:
        self.listing = listing
        self.listed_body = listed
        self.answer = answer
        self.listed = 0
        self.completions = 0
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith(self.listing):
            with self._lock:
                self.listed += 1
            time.sleep(0.1)
            return httpx.Response(200, json=self.listed_body)
        with self._lock:
            self.completions += 1
        return httpx.Response(200, json=self.answer)


class TestAModelIsReachedOnceHoweverManyAskAtOnce:
    """R9.19 row 1's precondition: what a run does once, it still does once."""

    def test_the_client_is_built_once(self, monkeypatch):
        """The one where three workers make a run's first call together.

        The client is built at the first cache miss and not before (R9.2 row
        5). Three first misses at once are still one first miss.
        """
        import dossier.cli.bootstrap as cli

        built: list[str] = []

        class Answering:
            model_id = MODEL

            def complete(self, prompt: str, *, schema=None, parts=()) -> str:
                return "answered"

        def build(model_id: str) -> Answering:
            built.append(model_id)
            time.sleep(0.1)
            return Answering()

        monkeypatch.setattr(cli, "build_model_client", build)
        lazy = cli.BuiltOnFirstCall(MODEL)

        _at_once(3, lambda: lazy.complete("x"))

        assert built == [MODEL]

    def test_an_ollama_digest_is_asked_for_once(self):
        """The one R9.4 row 1 makes: one digest request for the run, not one per call."""
        digest = "7f3c29a1" * 8
        server = _SlowServer(
            "/api/tags",
            {"models": [{"name": "qwen2.5:7b", "digest": digest}]},
            {"message": {"role": "assistant", "content": "answered"}},
        )
        client = ollama(
            f"ollama:qwen2.5:7b@sha256:{digest}",
            url="http://localhost:11434",
            api_key=None,
            transport=httpx.MockTransport(server),
        )

        _at_once(3, lambda: client.complete("x"))

        assert (server.listed, server.completions) == (1, 3)

    def test_a_served_repository_is_asked_for_once(self):
        """The same, for R9.6: vLLM is asked what it serves once."""
        repository = "Qwen/Qwen2.5-7B-Instruct"
        server = _SlowServer(
            "/models",
            {"object": "list", "data": [{"id": repository, "root": repository}]},
            {"choices": [{"message": {"content": "answered"}}]},
        )
        client = hf(
            f"hf:{repository}@" + "1c0f8e6b" * 5,
            url="http://gpu-01:8000/v1",
            api_key=None,
            transport=httpx.MockTransport(server),
        )

        _at_once(3, lambda: client.complete("x"))

        assert (server.listed, server.completions) == (1, 3)
