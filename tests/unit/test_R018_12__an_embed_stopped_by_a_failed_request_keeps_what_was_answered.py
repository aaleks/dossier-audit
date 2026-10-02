"""R18.12 — an `embed` stopped by a failed request keeps every vector answered
before it.

The vectors were cached only once every request had answered, so a request
failing late threw away every vector the `embed` had been answered, and the
next one asked for all of them again: hours, on a CPU. Here seventy one-chunk
notes are embedded in requests of 32, by a model whose third request fails.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from tests.fakes import FakeEmbeddingProvider
from tests.unit.test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss import embed, note

NOTES = [note(f"INC-{4900 + at}", f"Note {at}: the checkout timed out.\n") for at in range(70)]


class Stopped(RuntimeError):
    """What a request that failed raises, as far as `embed` can tell."""


class FailingModel(FakeEmbeddingProvider):
    """Answers each request at the length its place says, and fails the one at `failing`."""

    def __init__(self, *, lengths: Sequence[int] = (2560, 2560), failing: int = 3) -> None:
        super().__init__()
        self.lengths, self.failing = lengths, failing

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        place = len(self.requests) + 1
        if place == self.failing:
            self.requests.append(list(texts))
            raise Stopped("POST http://localhost:11434/api/embed failed: timed out")
        self.dimensions = self.lengths[place - 1]
        return super().embed(texts)


class TestAnEmbedStoppedByAFailedRequestKeepsWhatWasAnswered:
    """R18.12 — what was answered before the failure is kept, when its lengths agree."""

    def test_the_vectors_answered_before_the_failure_are_kept(self, workspace: Path):
        """Row 1 — the one whose third request of 32 failed."""
        with pytest.raises(Stopped):
            embed(workspace, NOTES, FailingModel())
        again = FakeEmbeddingProvider()

        embed(workspace, NOTES, again)

        assert [len(request) for request in again.requests] == [6]

    def test_lengths_that_disagree_keep_nothing(self, workspace: Path):
        """Row 2, counter-example — the one answered 2,560 values, then 1,024, then failing."""
        with pytest.raises(Stopped):
            embed(workspace, NOTES, FailingModel(lengths=(2560, 1024)))
        again = FakeEmbeddingProvider()

        embed(workspace, NOTES, again)

        assert [len(request) for request in again.requests] == [32, 32, 6]

    def test_every_vector_answered_is_kept(self, workspace: Path):
        """Row 3, counter-example — the one every request answered."""
        embed(workspace, NOTES, FakeEmbeddingProvider())
        again = FakeEmbeddingProvider()

        embed(workspace, NOTES, again)

        assert again.requests == []
