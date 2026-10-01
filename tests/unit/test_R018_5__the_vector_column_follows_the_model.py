"""R18.5 — the vector column's type follows the length of the model's vectors.

pgvector indexes a `vector` of up to 2,000 dimensions and a `halfvec` of up to
4,000. Qwen3-Embedding-4B answers 2,560, so its vectors are held at half
precision, which is what its fp16 weights produce anyway. A vector of another
length than the index holds is refused before anything is written: one index
holds one model's vectors.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fakes import FakeEmbeddingProvider, FakeIndexSink
from tests.unit.test_R018_3__a_chunk_is_embedded_only_on_a_cache_miss import embed, note

from dossier.domain.index import vector_column


class ShortForOne(FakeEmbeddingProvider):
    """A model answering 1,024 values for `INC-4821`'s text, as another model would."""

    def _vector(self, text: str) -> list[float]:
        vector = super()._vector(text)
        return vector[:1024] if "48'200" in text else vector


class TestTheVectorColumnFollowsTheModel:
    """R18.5 — the column a model's vectors fit, or none."""

    def test_qwen3_embedding_is_held_at_half_precision(self):
        """Row 1 — the one whose 2,560 values are past `vector`'s limit."""
        assert vector_column(2560) == "halfvec(2560)"

    def test_two_thousand_values_fit_a_vector(self):
        """Row 2 — the one at `vector`'s limit."""
        assert vector_column(2000) == "vector(2000)"

    def test_one_past_the_limit_is_a_halfvec(self):
        """Row 3 — the one a value past it."""
        assert vector_column(2001) == "halfvec(2001)"

    def test_past_halfvecs_limit_nothing_indexes_it(self):
        """Row 4, counter-example — the one at 4,001 values."""
        with pytest.raises(ValueError) as refused:
            vector_column(4001)

        assert str(refused.value) == (
            "a vector of 4001 values: pgvector indexes a vector of up to 2,000 "
            "dimensions and a halfvec of up to 4,000, and no type indexes this"
        )

    def test_a_vector_of_another_length_is_refused_and_nothing_written(self, tmp_path: Path):
        """Row 5, counter-example — the one answered 1,024 values, the others 2,560.

        The odd vector sorts first, and is still the one named: the others'
        length is the index's, whichever chunk comes first.
        """
        from dossier.domain.chunks import HEADINGS_CHUNKER, chunk_id
        from dossier.infrastructure.cache import ArtifactCache

        sink = FakeIndexSink()
        documents = [
            note("INC-4821", "# INC-4821\n\nFinance confirmed CHF 48'200.\n"),
            note("INC-4822", "# INC-4822\n\nFinance confirmed CHF 12'500.\n"),
            note("INC-4901", "# INC-4901\n\nFinance confirmed CHF 0.00.\n"),
        ]
        odd = chunk_id(
            document_id="incidents-jira:INC-4821",
            chunker=HEADINGS_CHUNKER,
            settings={"max_chars": 2000},
            index=0,
            text="Finance confirmed CHF 48'200.",
        )

        with pytest.raises(ValueError) as refused:
            embed(tmp_path, documents, ShortForOne(), sink=sink)

        assert str(refused.value) == (
            f"incidents-jira:INC-4821: chunk {odd[:12]} was answered 1024 values, and "
            "the index holds vectors of 2560. One index holds one model's vectors: "
            "nothing is written"
        )
        assert sink.writes == 0
        assert sink.columns == {}
        assert ArtifactCache(tmp_path, namespace="embed").all_keys() == []
