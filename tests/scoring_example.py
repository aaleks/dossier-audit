"""`_fixtures.md`'s scoring and comparison examples, as a source and a model.

Four incidents an issue-tracker source holds, keyed by the incident itself as a
tracker reports it (the gold set is keyed the same way), and what a run answers
for each: run `a` is the scoring example (R7.2), run `b` the comparison example
(R7.8). Every answer cites a span its document really holds, so every verdict is
about the value and none is about grounding (R7.4).

Not a fixture: tests build the source and the model from this data, so a test
can hand a source a fifth document or a model a second set of answers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import datetime

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem

PIPELINE = "incident-audit"
SOURCE_ID = "incidents-jira"
SOURCE_TYPE = "issue-tracker"
FIELDS = ("loss_amount", "resolution_date", "severity", "affected_systems", "root_cause")

ISSUES = {
    "INC-4821": (
        "# INC-4821\n\n"
        "Finance confirmed a total exposure CHF 48'200 in late-settlement interest.\n"
        "Resolved on 2026-07-28.\n"
        "Severity was assessed as major.\n"
        "Affected systems: payments-api, ledger-batch.\n"
    ),
    "INC-4822": (
        "# INC-4822\n\n"
        "Finance confirmed a total exposure CHF 12'500.\n"
        "Resolved on 2026-08-04.\n"
        "Severity was assessed as minor.\n"
        "Affected systems: ledger-batch.\n"
        "An early guess was disk pressure on the batch host; nobody confirmed it.\n"
    ),
    "INC-4901": (
        "# INC-4901\n\n"
        "Finance confirmed a total exposure CHF 0.00.\n"
        "Resolved on 2026-08-11; the ticket was closed on 2026-08-12.\n"
        "Severity was assessed as critical.\n"
        "Affected systems: payments-api.\n"
    ),
    "INC-5455": (
        "# INC-5455\n\n"
        "Finance confirmed a total exposure CHF 3'100.\n"
        "Resolved on 2026-08-19.\n"
        "Severity was assessed as major.\n"
        "Affected systems: upload-service. payments-api was checked and ruled out.\n"
        "Root cause undetermined; the competing hypotheses include an unbounded "
        "retry loop.\n"
    ),
}

# The corpus postmortem (`_fixtures.md`) that makes two runs cover different
# documents (R7.8 row 3). It has no gold file, and needs none: a comparison over
# different documents is refused before anything is scored.
FIFTH_ISSUE = {
    "INC-5102": (
        "# INC-5102\n\n"
        "orders-api pods were OOMKilled under a retry storm; order submission degraded.\n"
    ),
}


def found(document: str, field: str, value, span: str, **extra) -> dict:
    return {
        "field": field,
        "value": value,
        **extra,
        "source": {"document": document, "span": span},
    }


def abstains(field: str) -> dict:
    return {"field": field, "value": None, "reason": "not stated in document"}


def _loss(document: str, amount: float, written: str) -> dict:
    return found(
        document, "loss_amount", amount, f"total exposure CHF {written}", currency="CHF"
    )


# Run `a`: gold's value everywhere except the four disagreements of the scoring
# example (R7.2).
ANSWERS = {
    "INC-4821": [
        _loss("INC-4821", 48200.00, "48'200"),
        found("INC-4821", "resolution_date", "2026-07-28", "Resolved on 2026-07-28"),
        found("INC-4821", "severity", "major", "Severity was assessed as major"),
        found(
            "INC-4821",
            "affected_systems",
            "payments-api, ledger-batch",
            "Affected systems: payments-api, ledger-batch",
        ),
        abstains("root_cause"),
    ],
    "INC-4822": [
        _loss("INC-4822", 12500.00, "12'500"),
        found("INC-4822", "resolution_date", "2026-08-04", "Resolved on 2026-08-04"),
        found("INC-4822", "severity", "minor", "Severity was assessed as minor"),
        found("INC-4822", "affected_systems", "ledger-batch", "Affected systems: ledger-batch"),
        # Disagreement: gold abstains, the run took an unconfirmed guess as the cause.
        found(
            "INC-4822",
            "root_cause",
            "disk pressure on the batch host",
            "disk pressure on the batch host",
        ),
    ],
    "INC-4901": [
        _loss("INC-4901", 0.00, "0.00"),
        # Disagreement: the run read the date the ticket closed, not the resolution.
        found(
            "INC-4901", "resolution_date", "2026-08-12", "the ticket was closed on 2026-08-12"
        ),
        found("INC-4901", "severity", "critical", "Severity was assessed as critical"),
        found("INC-4901", "affected_systems", "payments-api", "Affected systems: payments-api"),
        abstains("root_cause"),
    ],
    "INC-5455": [
        _loss("INC-5455", 3100.00, "3'100"),
        found("INC-5455", "resolution_date", "2026-08-19", "Resolved on 2026-08-19"),
        found("INC-5455", "severity", "major", "Severity was assessed as major"),
        # Disagreement: the run named the system that was ruled out.
        found(
            "INC-5455",
            "affected_systems",
            "payments-api",
            "payments-api was checked and ruled out",
        ),
        # Disagreement: gold abstains, the run picked one competing hypothesis.
        found("INC-5455", "root_cause", "an unbounded retry loop", "an unbounded retry loop"),
    ],
}

# Run `b`: gold's value everywhere except the two disagreements of the
# comparison example (R7.8) -- both in `affected_systems`, which is what makes it
# regress while every other field holds or improves.
ANSWERS_AFTER = {
    "INC-4821": ANSWERS["INC-4821"],
    "INC-4822": [
        _loss("INC-4822", 12500.00, "12'500"),
        found("INC-4822", "resolution_date", "2026-08-04", "Resolved on 2026-08-04"),
        found("INC-4822", "severity", "minor", "Severity was assessed as minor"),
        # Disagreement: the run named the host from the unconfirmed guess.
        found("INC-4822", "affected_systems", "the batch host", "the batch host"),
        abstains("root_cause"),
    ],
    "INC-4901": [
        _loss("INC-4901", 0.00, "0.00"),
        found("INC-4901", "resolution_date", "2026-08-11", "Resolved on 2026-08-11"),
        found("INC-4901", "severity", "critical", "Severity was assessed as critical"),
        found("INC-4901", "affected_systems", "payments-api", "Affected systems: payments-api"),
        abstains("root_cause"),
    ],
    "INC-5455": [
        _loss("INC-5455", 3100.00, "3'100"),
        found("INC-5455", "resolution_date", "2026-08-19", "Resolved on 2026-08-19"),
        found("INC-5455", "severity", "major", "Severity was assessed as major"),
        # Disagreement, still: the system that was ruled out.
        found(
            "INC-5455",
            "affected_systems",
            "payments-api",
            "payments-api was checked and ruled out",
        ),
        abstains("root_cause"),
    ],
    "INC-5102": [abstains(field) for field in FIELDS],
}


class IssueTracker:
    """A source keyed by incident, as an issue tracker is. No network, no markers.

    Holds whatever it is handed and reads it on every call, so a test can add a
    document between two syncs.
    """

    lists_everything = False

    media_type = "text/markdown"

    def __init__(self, issues: Mapping[str, str]) -> None:
        self.issues = dict(issues)

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        for key in sorted(self.issues):
            yield ItemRef(key=key, remote_version=None, updated_at=None)

    def fetch(self, key: str) -> RawItem:
        return RawItem(
            key=key,
            payload=self.issues[key].encode("utf-8"),
            media_type=self.media_type,
            remote_version=None,
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class RoutedModel:
    """A model answering each document with its own scripted answer.

    Routed by the document in the prompt rather than consumed in order, so a test
    does not depend on the order a run visits documents in. It counts calls.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, answers: Mapping[str, list[dict]]) -> None:
        self.answers = answers
        self.calls: list[str] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        asked = [key for key in self.answers if f"# {key}\n" in prompt]
        assert len(asked) == 1, f"expected one document in the prompt, found {asked}"
        self.calls.append(asked[0])
        return json.dumps({"document": asked[0], "fields": self.answers[asked[0]]})
