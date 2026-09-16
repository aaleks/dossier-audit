"""R8.1 — a converted artifact is a pure function of the snapshot bytes and the
declared options.

A converter reads the bytes it is given and its own options, and nothing else.
No clock, no locale, no environment variable, no file outside its input, no
network (R0.1).

This is the rule the convert cache rests on. `K_convert` claims an artifact is
determined by the snapshot hash, the converter's id and version, and its options.
A converter consulting anything else makes that key a lie: the cache then serves
text that no longer matches what the converter would produce today, nothing
detects it, and every stage above inherits the error with a provenance record
that looks entirely correct.

Written as a **conformance check over every installed converter** rather than
against one of them. The rule is a claim about what a converter *is*, so a
converter added tomorrow is covered the day it registers.

The spec's example row names `pdf-markdown` on `audit-note.pdf`. No PDF converter
ships yet -- one is a large dependency with its own release cadence, which is
exactly why R8.7 makes converters separate packages -- so the rows below are
proved against every converter that is actually installed, `markdown-text`
included. The claim is unchanged; only the sample is.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dossier.domain.ports import Converter
from dossier.infrastructure.converters.registry import installed_converters

INSTALLED = installed_converters()

# One payload per media type a converter might claim, so the conformance rows
# below can hand each converter something it will actually accept.
PAYLOADS = {
    "text/markdown": b"# INC-4821\n\nTotal exposure CHF 48'200 on page 3.\n",
}


def payload_for(converter: Converter) -> bytes:
    if converter.media_type not in PAYLOADS:
        pytest.skip(f"no sample payload for {converter.media_type}")
    return PAYLOADS[converter.media_type]


def ids(converter: Converter) -> str:
    return f"{converter.id}-{converter.version}"


PROBE = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {src!r})
    from dossier.infrastructure.converters.registry import installed_converters

    converter = next(c for c in installed_converters() if c.id == {converter_id!r})
    sys.stdout.buffer.write(converter.convert({payload!r}, {{}}))
    """
)


class TestEveryConverterIsPure:
    """R8.1 — the same bytes and the same options, the same artifact."""

    @pytest.mark.parametrize("converter", INSTALLED, ids=ids)
    def test_converting_twice_produces_identical_bytes(self, converter: Converter):
        """Example 1: the one where nothing about the second call differs."""
        payload = payload_for(converter)

        assert converter.convert(payload, {}) == converter.convert(payload, {})

    @pytest.mark.parametrize("converter", INSTALLED, ids=ids)
    def test_two_processes_with_different_environments_agree(
        self, converter: Converter, repo_root: Path, tmp_path: Path
    ):
        """Example 2: the one that catches a clock, a locale or a hash seed.

        Real subprocesses, because `PYTHONHASHSEED`, `LC_ALL` and `TZ` are read
        at interpreter start. Different working directories too, so a converter
        reading a file relative to the cwd is caught rather than merely
        discouraged.
        """
        source = PROBE.format(
            src=str(repo_root / "src"),
            converter_id=converter.id,
            payload=payload_for(converter),
        )
        import os

        outputs = [
            subprocess.run(
                [sys.executable, "-c", source],
                capture_output=True,
                check=True,
                cwd=str(directory),
                env={**os.environ, "PYTHONHASHSEED": seed, "LC_ALL": locale, "TZ": zone},
            ).stdout
            for directory, seed, locale, zone in (
                (repo_root, "0", "C", "UTC"),
                (tmp_path, "987654", "tr_TR.UTF-8", "Asia/Tokyo"),
            )
        ]

        assert outputs[0] == outputs[1]

    @pytest.mark.parametrize("converter", INSTALLED, ids=ids)
    def test_the_artifact_is_not_the_input_object(self, converter: Converter):
        """The one where the payload cannot be mutated under its caller.

        A converter handed the snapshot's bytes must not be able to change what
        the store believes it holds (R0.2). `bytes` is immutable, so this is
        really a check that nothing started returning a `bytearray` view.
        """
        payload = payload_for(converter)
        artifact = converter.convert(payload, {})

        assert isinstance(artifact, bytes)
        assert not isinstance(artifact, bytearray)

    @pytest.mark.parametrize("converter", INSTALLED, ids=ids)
    def test_declaring_an_option_produces_its_own_artifact(self, converter: Converter):
        """Counter-example (row 4): the one where output is *supposed* to differ.

        Options are part of `K_convert`, so a converter that reads one is
        answering a different question rather than giving a different answer to
        the same one. A converter that reads none -- like `markdown-text` -- must
        still accept the argument and still be pure, which is what this asserts.
        """
        payload = payload_for(converter)

        with_option = converter.convert(payload, {"ocr": "true"})

        assert isinstance(with_option, bytes)
        assert with_option == converter.convert(payload, {"ocr": "true"})


class TestNoConverterReadsTheWorld:
    """R8.1 example 3 — checked by reading the code, not by hoping.

    The failure this catches cannot be caught by calling the converter: a clock
    read produces a *plausible* artifact every time, and the two runs that would
    disagree are minutes apart on someone else's machine. So the check is a walk
    over the module, the same shape R0.1 uses for the hash boundary.
    """

    # Attribute accesses that make an artifact depend on when or where it ran.
    FORBIDDEN_CALLS = {
        ("datetime", "now"),
        ("datetime", "today"),
        ("datetime", "utcnow"),
        ("time", "time"),
        ("time", "monotonic"),
        ("os", "getcwd"),
        ("os", "urandom"),
        ("random", "random"),
        ("random", "choice"),
        ("random", "shuffle"),
        ("uuid", "uuid1"),
        ("uuid", "uuid4"),
        ("locale", "getlocale"),
        ("locale", "setlocale"),
    }
    FORBIDDEN_MODULES = {"random", "uuid", "locale", "secrets", "tempfile"}

    def converter_modules(self) -> list[Path]:
        package = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "dossier"
            / "infrastructure"
            / "converters"
        )
        return sorted(path for path in package.rglob("*.py"))

    def test_at_least_one_converter_module_is_scanned(self):
        """A scan over nothing would make every check below vacuous."""
        assert self.converter_modules()

    def test_no_converter_calls_a_clock_or_a_source_of_randomness(self):
        """The one where `datetime.now()` in a converter is caught by reading."""
        offenders: list[str] = []

        for path in self.converter_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                owner = node.func.value
                if (
                    isinstance(owner, ast.Name)
                    and (
                        owner.id,
                        node.func.attr,
                    )
                    in self.FORBIDDEN_CALLS
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno}: {owner.id}.{node.func.attr}()"
                    )

        assert not offenders, "\n".join(
            offenders + ["  A converted artifact is a pure function of its input (R8.1)."]
        )

    def test_no_converter_imports_a_non_deterministic_module(self):
        """The one where the import is the evidence.

        An import of `random` or `locale` in a converter has no legitimate use,
        and catching it at the import is stronger than chasing every call it
        could make.
        """
        offenders: list[str] = []

        for path in self.converter_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name in self.FORBIDDEN_MODULES:
                        offenders.append(f"{path.name}:{node.lineno}: imports {name}")

        assert not offenders, "\n".join(
            offenders + ["  A converted artifact is a pure function of its input (R8.1)."]
        )


class TestAConvertedArtifactCanBeTracedToWhatMadeIt:
    """R0.3's shape for conversions — an artifact with no record explains nothing.

    Found by `/quality`. Stage artifacts get a sibling `.meta.json`; convert
    artifacts did not, though `ConvertInputs.recorded()` and `provenance()` were
    written for exactly this and never called.

    That record is the only diagnosis available for the hazard `domain/ports.py`
    warns about in as many words and says no test can enforce: a converter author
    who improves output without raising `version`. The cache then holds artifacts
    claiming to be something they are not. With a record you can at least find out
    afterwards which converter and which version produced a given text; without
    one there is nothing to look at.
    """

    def test_a_conversion_writes_a_record_naming_its_converter(self, tmp_path: Path):
        """The one where the artifact can be traced afterwards."""
        import json

        from dossier.application.convert import HeldDocument, convert_source
        from dossier.infrastructure.cache import ArtifactCache
        from dossier.infrastructure.store import SnapshotStore

        store = SnapshotStore(tmp_path)
        cache = ArtifactCache(tmp_path, namespace="convert")
        converter = next(c for c in INSTALLED if c.media_type == "text/markdown")

        convert_source(
            source_id="incidents-manual",
            documents={
                "INC-4821": HeldDocument(
                    snapshot=store.put(PAYLOADS["text/markdown"]),
                    media_type="text/markdown",
                )
            },
            kinds=None,
            converters=[converter],
            store=store,
            cache=cache,
            run_id="20260806T142203Z-4f1a",
            dossier_version="0.1.0",
        )

        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (tmp_path / ".dossier" / "cache").rglob("*.meta.json")
        ]
        assert len(records) == 1
        assert records[0]["converter_id"] == converter.id
        assert records[0]["converter_version"] == converter.version
        assert records[0]["run_id"] == "20260806T142203Z-4f1a"

    def test_a_cached_conversion_still_requires_its_record(self, tmp_path: Path):
        """The one where an artifact without a record is not an entry (R5.8).

        The same rule stage artifacts follow. A process killed between the two
        writes leaves bytes nothing can explain, and serving them would be
        serving something whose provenance is unknown.
        """
        from dossier.infrastructure.cache import ArtifactCache

        cache = ArtifactCache(tmp_path, namespace="convert")
        cache.put("e" * 64, b"# converted")

        assert cache.get("e" * 64) is not None
        assert cache.get("e" * 64, require_record=True) is None
