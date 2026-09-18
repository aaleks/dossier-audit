"""R8.11 — a conversion that produces several parts produces one container.

R8.4 says one declared conversion is one artifact with one key. A page-images
conversion of a forty-page PDF is forty pictures, so the parts travel together
in a container that is a pure function of its contents -- which is what makes
R8.1's byte-identical promise achievable for an artifact that is not one blob.

The rows below are the rule's example table, transcribed. The rows naming
`pdf-images` are in `test_R008_11__pdf_images_renders_every_page.py`, which is
where the binary fixture lives.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dossier.domain.conversion import pack_parts, part_name, unpack_parts

REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")

PARTS = [b"\x89PNG first", b"\x89PNG second", b"\x89PNG third"]

PROBE = textwrap.dedent(
    """
    import hashlib, sys
    sys.path.insert(0, {src!r})
    from dossier.domain.conversion import pack_parts

    packed = pack_parts([b"a", b"bb", b"ccc"], suffix=".png")
    sys.stdout.write(hashlib.sha256(packed).hexdigest())
    """
)


class TestThePartsTravelTogether:
    """R8.11 — one artifact, in part order, byte-identical everywhere."""

    def test_the_parts_are_named_by_position_from_one(self):
        """Example 1: the one where a reader counts pages, not indices.

        Zero-padded so that page 2 sorts before page 10 in any listing, and
        1-based because a reader turns to page 1 (R6.14's reasoning, same
        reader).
        """
        assert part_name(1, ".png") == "page-001.png"
        assert part_name(3, ".png") == "page-003.png"
        assert sorted([part_name(2, ".png"), part_name(10, ".png")]) == [
            "page-002.png",
            "page-010.png",
        ]

    def test_a_container_round_trips_to_the_same_ordered_parts(self):
        """Example 4: the one where a converter and a step must agree.

        The format has exactly one definition. If packing and unpacking were
        written separately, a step would read what a converter meant to write
        rather than what it wrote.
        """
        assert unpack_parts(pack_parts(PARTS, suffix=".png")) == PARTS

    def test_packing_the_same_parts_twice_produces_identical_bytes(self):
        """Example 2: the one where nothing about the second call differs.

        The obvious way to write a container is a ZIP with real timestamps,
        which fails this within one second of itself.
        """
        assert pack_parts(PARTS, suffix=".png") == pack_parts(PARTS, suffix=".png")

    def test_two_processes_with_different_environments_agree(self):
        """Example 2: the one where nothing about the machine reaches the bytes.

        A different `PYTHONHASHSEED` and a different working directory, because
        both are how an artifact stops being byte-identical across machines
        without anything in a diff to explain it (R0.4, R5.6).
        """
        script = PROBE.format(src=REPO_SRC)
        digests = {
            subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                check=True,
                cwd=cwd,
                env={"PATH": "", "PYTHONHASHSEED": seed, "SYSTEMROOT": ""},
            ).stdout
            for cwd, seed in ((Path(REPO_SRC), "0"), (Path(__file__).parent, "12345"))
        }

        assert len(digests) == 1, "the container differs between processes"

    def test_one_part_is_still_a_container(self):
        """Example 3's shape: the one where a document has a single page.

        A container of one, not the part itself. A step unpacks whatever it is
        given, and a format that collapsed at one part would make the step's
        behaviour depend on the page count of the document it was handed.
        """
        packed = pack_parts([PARTS[0]], suffix=".png")

        assert packed != PARTS[0]
        assert unpack_parts(packed) == [PARTS[0]]

    def test_no_parts_is_an_empty_container_and_not_an_error(self):
        """The boundary: the one where a PDF has no pages at all.

        Empty rather than a raise. A zero-page document is a strange document
        and not a broken conversion -- R8.6 is for a converter that could not
        read its input, and this one read it fine.
        """
        assert unpack_parts(pack_parts([], suffix=".png")) == []

    def test_bytes_that_are_not_a_container_are_refused(self):
        """Counter-example: the one where a step was handed the wrong kind.

        A `ValueError` rather than a silent empty list. A step reading
        `documents@page_images` and quietly receiving no pages would audit
        nothing and say it audited a document.
        """
        with pytest.raises(ValueError, match="container"):
            unpack_parts(b"this is a markdown artifact, not a container")
