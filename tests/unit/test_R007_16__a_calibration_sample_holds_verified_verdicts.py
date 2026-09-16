"""R7.16 — a calibration sample records candidate answers a human marked
supported or unsupported.

The gold set and the sample answer different questions. A gold file says what the
right value *is*; a sample record says whether a *candidate* answer is supported
by its document, which is the question a judge is asked and the only one its
agreement can be measured on. So a sample must be able to hold an answer that is
wrong -- R7.12's planted case is exactly that, and a gold file has nowhere to put
one.

One record per line at `gold/<name>/samples/<field>.jsonl`. The four a
measurement needs are the document, the candidate answer, the verdict and the
reviewer; a record may carry more, and the sample committed at
`tests/evals/golden/root_cause.jsonl` does -- which the last test here reads, so
that the file this rule describes cannot fail the rule describing it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.config.load import ConfigError

FIELD = "root_cause"
COMMITTED = Path(__file__).resolve().parents[1] / "evals" / "golden" / "root_cause.jsonl"

# `rc-01` and `rc-02` of the committed sample, in shape: one supported, one the
# planted claim R7.12 turns on. Extra keys on purpose -- a reviewer's sample
# carries its own bookkeeping, and a record is not wrong for saying more than
# the four a measurement reads.
SUPPORTED = {
    "id": "rc-01",
    "field": FIELD,
    "document": "INC-4830",
    "answer": "The renewed TLS certificate was issued into Vault but never deployed.",
    "supported": True,
    "reason": "Section 4 states exactly this.",
    "verified_by": "a.aleks",
    "verified_at": "2026-09-15",
}
PLANTED = {
    "id": "rc-02",
    "field": FIELD,
    "document": "INC-4830",
    "answer": "The quarter-end change freeze caused the checkout outage.",
    "supported": False,
    "reason": "The freeze is only a contributing factor; the document never says it caused it.",
    "verified_by": "a.aleks",
    "verified_at": "2026-09-15",
}


def _sample(root: Path, records: list[dict | str]) -> Path:
    """`gold/incidents/samples/root_cause.jsonl` holding `records`; the gold directory.

    A record may be given as a dict, or as raw text for the cases that are not
    valid to begin with.
    """
    directory = root / "gold" / "incidents"
    (directory / "samples").mkdir(parents=True, exist_ok=True)
    lines = [entry if isinstance(entry, str) else json.dumps(entry) for entry in records]
    (directory / "samples" / f"{FIELD}.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return directory


def _load(directory: Path):
    """The sample, read the way `dossier calibrate` will read it.

    Imported inside the helper rather than at module scope: until this lands,
    collecting the default suite would error on a name that does not exist yet,
    and a red collection is not the same as a red test.
    """
    from dossier.config.load import load_calibration_sample

    return load_calibration_sample(directory, FIELD)


class TestACalibrationSampleHoldsVerifiedVerdicts:
    """R7.16 — the document, the candidate answer, the verdict, and who said so."""

    def test_a_record_with_a_document_answer_verdict_and_reviewer_is_accepted(
        self, tmp_path: Path
    ):
        """Example 1: the one holding the whole shape a measurement needs.

        Both verdicts survive as real booleans, in file order. The planted case
        is the reason the sample exists at all: a gold file could hold the first
        record's claim, and has nowhere to put the second.
        """
        directory = _sample(tmp_path, [SUPPORTED, PLANTED])

        cases = _load(directory)

        assert [case.supported for case in cases] == [True, False]
        assert [case.document for case in cases] == ["INC-4830", "INC-4830"]
        assert cases[1].answer == PLANTED["answer"]
        assert cases[1].verified_by == "a.aleks"

    def test_a_record_with_no_reviewer_is_refused_naming_the_line(self, tmp_path: Path):
        """Example 2: the one nobody stood behind.

        There is no anonymous path into what a judge is measured against, for the
        same reason there is none into the gold set (R7.7). The line number is
        named because a sample is a long file and "somewhere in here" is not a
        fix anyone can act on.
        """
        anonymous = {key: value for key, value in PLANTED.items() if key != "verified_by"}
        directory = _sample(tmp_path, [SUPPORTED, anonymous])

        with pytest.raises(ConfigError) as error:
            _load(directory)

        assert "verified_by" in str(error.value)
        assert "2" in str(error.value), "the line the bad record is on"

    def test_a_verdict_written_as_a_string_is_refused_naming_the_line(self, tmp_path: Path):
        """Example 3: the one where `supported` is `"false"` rather than `false`.

        The row with teeth. Every non-empty string is truthy, so a loader that
        took this at face value would read `"false"` as *supported* and score the
        judge against the opposite of what the reviewer meant -- then report a
        percentage for it. Refused rather than coerced: a sample this malformed
        is a sample whose author has to be told.
        """
        stringly = {**PLANTED, "supported": "false"}
        directory = _sample(tmp_path, [SUPPORTED, stringly])

        with pytest.raises(ConfigError) as error:
            _load(directory)

        assert "supported" in str(error.value)
        assert "2" in str(error.value), "the line the bad record is on"

    def test_a_gold_answer_is_not_a_sample_record(self, tmp_path: Path):
        """Counter-example (row 4): the one shaped like a gold file's field entry.

        It says what the answer *is*, and nothing about whether a candidate is
        supported. Refused rather than half-read, because a sample of these would
        measure a judge against verdicts nobody recorded.
        """
        gold_entry = {
            "document": "INC-4821",
            "value": None,
            "reason": "not stated in document",
            "verified_by": "a.aleks",
            "verified_at": "2026-08-14",
        }
        directory = _sample(tmp_path, [gold_entry])

        with pytest.raises(ConfigError):
            _load(directory)

    def test_the_committed_sample_satisfies_the_rule_that_describes_it(self, tmp_path: Path):
        """The sample R7.11 was measured on, read as R7.16 says a sample is read.

        Not a transcribed row: a guard. That file carries `id`, `rule`, `field`
        and `path` beyond the four a measurement needs, so a reader that forbade
        unknown keys would reject the only real sample in the repository while
        every hand-written test above still passed.
        """
        directory = _sample(
            tmp_path,
            [
                line
                for line in COMMITTED.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ],
        )

        cases = _load(directory)

        assert len(cases) == 20, "the twenty human-scored cases R7.11 measures"
        assert sum(1 for case in cases if case.supported) == 12
