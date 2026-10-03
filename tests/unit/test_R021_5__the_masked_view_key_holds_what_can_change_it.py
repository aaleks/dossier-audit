"""R21.5 — the masked view is keyed by the converted text, the masker's id and
version, `MASKING_VERSION` and the declaration, and nothing else re-masks it.

`K_mask` is a pure composition (spec 021, "The masked view"), proved here
without a masker or a workspace. That the masker is then asked 0 times on a
hit is the cache's promise (R5.5), and R21.6 is the claim that a replay reads
the view through this key.
"""

from __future__ import annotations

TEXT = "# PLAY-6001\n\nErika Mustermann called. The Oracle database stalled.\n"
CID_YAML = (
    b"masker: presidio\nlanguages: [en]\nscore_threshold: 0.5\n"
    b"entities: [PERSON, ORGANIZATION]\nallow: masking/allow.txt\n"
)


def _key(text: str = TEXT, *, version: str = "1.0.0", files=None) -> str:
    from dossier.domain.keys import cache_key, mask_inputs
    from dossier.domain.masking import declaration_hash

    declared = (
        files if files is not None else {"masking/cid.yaml": CID_YAML, "masking/allow.txt": b""}
    )
    return cache_key(
        mask_inputs(
            text=text,
            masker_id="presidio",
            masker_version=version,
            declaration=declaration_hash(declared),
        )
    )


class TestTheMaskedViewKeyHoldsWhatCanChangeIt:
    """R21.5 — `K_mask`, composed of exactly what can change a masked view."""

    def test_a_file_the_declaration_names_is_part_of_its_hash(self):
        """Row 1: the one where `allow.txt` gains `Oracle`."""
        before = _key(files={"masking/cid.yaml": CID_YAML, "masking/allow.txt": b""})
        after = _key(files={"masking/cid.yaml": CID_YAML, "masking/allow.txt": b"Oracle\n"})

        assert before != after

    def test_a_new_masker_version_re_masks(self):
        """Row 2: the one where the masker's version `1.0.0` becomes `1.1.0`."""
        assert _key(version="1.0.0") != _key(version="1.1.0")

    def test_only_a_document_whose_masked_view_differs_moves_its_stage_keys(self):
        """Row 3: the one where masking is declared over a masked and a clean document.

        A stage key holds the hash of the text a model is shown. `PLAY-6001`'s
        masked view differs from its text; `INC-4821`, in which nothing is
        detected, is the same text, and so the same stage input.
        """
        from dossier.domain.hashing import content_hash
        from dossier.domain.masking import Detection, masked

        start = TEXT.index("Erika Mustermann")
        person = Detection(start=start, end=start + 16, entity="PERSON", score=0.85)
        clean = "# INC-4821\n\nFinance confirmed a total exposure CHF 48'200.\n"

        assert content_hash(masked(TEXT, [person]).encode()) != content_hash(TEXT.encode())
        assert content_hash(masked(clean, []).encode()) == content_hash(clean.encode())

    def test_the_same_text_from_another_converter_is_the_same_key(self):
        """Row 4: the one where `pdf-markdown` raises its version and the text is unchanged.

        The key holds the text, not who made it: a converter that writes the
        same words again is not a reason to mask them again.
        """
        assert _key(TEXT) == _key(str(TEXT))
        assert _key(TEXT) != _key(TEXT + "\n")

    def test_the_key_holds_nothing_a_prompt_or_a_run_could_move(self):
        """Row 5, a counter-example: the one where a prompt edit masks nothing.

        The canonical form is exactly the five things a masked view is a
        function of. A prompt, a step, a model and a run id are not among
        them, so editing `02_verify.md` cannot miss this cache.
        """
        from dossier.domain.keys import mask_inputs
        from dossier.domain.masking import MASKING_VERSION, declaration_hash

        keyed = mask_inputs(
            text=TEXT,
            masker_id="presidio",
            masker_version="1.0.0",
            declaration=declaration_hash({}),
        ).keyed()

        assert set(keyed) == {
            "kind",
            "text",
            "masker_id",
            "masker_version",
            "masking_version",
            "declaration",
        }
        assert keyed["masking_version"] == MASKING_VERSION
        assert "Erika" not in str(keyed), "a key holds a hash of the text, never its words"
