"""Leave this exercise's reviewer verdicts on a server, as MLflow's trace view would.

    python leave_verdicts.py http://127.0.0.1:5114              # the reviewers' first pass
    python leave_verdicts.py http://127.0.0.1:5114 --override   # j.okafor overrides s.brunner
    python leave_verdicts.py http://127.0.0.1:5114 --reject     # the rejected expectations go

The trace view is the way reviewers are meant to work, and a script cannot click
it. This makes the same calls the page makes, so every task can be finished
without a browser -- or checked after doing it in one:

  * a verdict is `mlflow.log_feedback` or `mlflow.log_expectation` on one trace,
    sourced `HUMAN`;
  * its author is the string `User`, because that is what the open-source trace
    view sends for everyone, whoever is logged in. One verdict below is logged
    under a real name instead, as a verdict logged through the API can be, so the
    difference is on the page and in the pull;
  * the trace view offers Edit only on a verdict whose author is `User` -- its
    own user, and so everyone's -- and changes it in place. A verdict under a
    real name it will not edit. Overriding one -- a new verdict naming the old
    one, which MLflow marks invalid -- is the API's `mlflow.override_feedback`.
    `--override` does that;
  * `Delete assessment` in the trace view is `mlflow.delete_assessment`. `--reject`
    does that, to the three expectations task 7 refuses.

The traces are found the way a reviewer finds them: the queue is the filter
tags.`dossier.review` = 'needed', and any one document's trace is
tags.`dossier.document` = '<key>'. A verdict goes on the newest trace of its
document.

Run twice, it leaves nothing twice: a verdict already on any trace of its
document -- valid, or overridden since -- is reported and skipped. So a verdict
you left by hand in task 3 is not left again. A verdict `--reject` deleted is
gone, and the first pass would leave it again, as a reviewer who insists would.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import mlflow
from mlflow import MlflowClient
from mlflow.entities import AssessmentSource

EXPERIMENT = "dossier-audit/incident-audit/run"
QUEUE = "tags.`dossier.review` = 'needed'"
TRACE_VIEW = "User"  # what the open-source trace view records as every verdict's author


@dataclass(frozen=True)
class Verdict:
    reviewer: str  # who a person would say left it -- MLflow is told `author`
    author: str  # the source_id MLflow records
    document: str
    kind: str  # "feedback" or "expectation"
    name: str
    value: object
    rationale: str | None = None


FIRST_PASS = [
    # s.brunner, in the trace view: the run was sure of PLAY-1002, and they are not.
    Verdict(
        reviewer="s.brunner",
        author=TRACE_VIEW,
        document="PLAY-1002.md",
        kind="feedback",
        name="severity",
        value=False,
        rationale="Two dashboards a day stale for a business morning is a missed "
        "reporting window, which the reporting SLA rates major, not minor.",
    ),
    Verdict(
        reviewer="s.brunner",
        author=TRACE_VIEW,
        document="PLAY-1002.md",
        kind="expectation",
        name="severity",
        value="major",
    ),
    # s.brunner again, through the API under their own name: in the queue, and wrong.
    Verdict(
        reviewer="s.brunner",
        author="s.brunner",
        document="PLAY-1001.md",
        kind="feedback",
        name="loss_amount",
        value=False,
        rationale="The quoted span is not in the note, which writes CHF 18'400, not 18,400.",
    ),
    # j.okafor, in the trace view.
    Verdict(
        reviewer="j.okafor",
        author=TRACE_VIEW,
        document="PLAY-1002.md",
        kind="expectation",
        name="severity",
        value="critical",
    ),
    Verdict(
        reviewer="j.okafor",
        author=TRACE_VIEW,
        document="PLAY-1002.md",
        kind="expectation",
        name="summary",
        value="The nightly export ran past the reporting window after a late warehouse load.",
    ),
    Verdict(
        reviewer="j.okafor",
        author=TRACE_VIEW,
        document="PLAY-1003.md",
        kind="expectation",
        name="severity",
        value="catastrophic",
    ),
    Verdict(
        reviewer="j.okafor",
        author=TRACE_VIEW,
        document="PLAY-1004.md",
        kind="feedback",
        name="overall",
        value=True,
        rationale="Every field is the one the note states.",
    ),
]

# j.okafor overrides s.brunner's thumbs-down. It carries a name other than `User`,
# so the trace view offers no Edit on it: the override is the API's.
OVERRIDE = Verdict(
    reviewer="j.okafor",
    author=TRACE_VIEW,
    document="PLAY-1001.md",
    kind="feedback",
    name="loss_amount",
    value=True,
    rationale="The value is right: CHF 18'400 is the figure the Impact section states. "
    "Only the quote is off, by one character.",
)

# What the maintainer rejects for good in task 8, by deleting it where it was left.
REJECTED = [
    ("PLAY-1002.md", "severity", "critical"),
    ("PLAY-1002.md", "summary", None),
    ("PLAY-1003.md", "severity", "catastrophic"),
]


def _value(assessment) -> object:
    said = assessment.feedback if assessment.feedback is not None else assessment.expectation
    return said.value


def _kind(assessment) -> str:
    return "feedback" if assessment.feedback is not None else "expectation"


def _human(trace) -> list:
    return [
        assessment
        for assessment in trace.info.assessments or []
        if str(assessment.source.source_type) == "HUMAN"
    ]


def _traces(client: MlflowClient, experiment: str, document: str) -> list:
    """Every trace of one document, newest first."""
    return list(
        client.search_traces(
            locations=[experiment],
            filter_string=f"tags.`dossier.document` = '{document}'",
            order_by=["timestamp_ms DESC"],
            include_spans=False,
        )
    )


def _shown(value: object) -> str:
    said = repr(value)
    return said if len(said) <= 15 else said[:14] + "…"


def _line(said: str, verdict: Verdict, trace: str) -> str:
    return (
        f"{said:<9}{verdict.document}  {verdict.kind:<12}{verdict.name:<13}"
        f"{_shown(verdict.value):<16}{verdict.author:<11}{verdict.reviewer:<11}{trace}"
    )


def show_queue(client: MlflowClient, experiment: str) -> None:
    queue = client.search_traces(
        locations=[experiment], filter_string=QUEUE, include_spans=False
    )
    print(f"queue    {QUEUE}  ·  {len(queue)} traces")
    for trace in sorted(queue, key=lambda each: each.info.tags["dossier.document"]):
        tags = trace.info.tags
        print(f"         {tags['dossier.document']}  {tags['dossier.findings']}")
    print()


def first_pass(client: MlflowClient, experiment: str) -> None:
    print(
        f"{'':<9}{'document':<14}{'kind':<12}{'name':<13}{'value':<16}{'author':<11}"
        f"{'for':<11}trace"
    )
    for verdict in FIRST_PASS:
        traces = _traces(client, experiment, verdict.document)
        if not traces:
            raise SystemExit(f"no trace of {verdict.document} in {EXPERIMENT}: run first")
        held = any(
            _kind(assessment) == verdict.kind
            and assessment.name == verdict.name
            and _value(assessment) == verdict.value
            for trace in traces
            for assessment in _human(trace)
        )
        trace = traces[0].info.trace_id
        if held:
            print(_line("already", verdict, trace))
            continue
        source = AssessmentSource(source_type="HUMAN", source_id=verdict.author)
        if verdict.kind == "feedback":
            mlflow.log_feedback(
                trace_id=trace,
                name=verdict.name,
                value=verdict.value,
                rationale=verdict.rationale,
                source=source,
            )
        else:
            mlflow.log_expectation(
                trace_id=trace, name=verdict.name, value=verdict.value, source=source
            )
        print(_line("left", verdict, trace))


def override(client: MlflowClient, experiment: str) -> None:
    for trace in _traces(client, experiment, OVERRIDE.document):
        for assessment in _human(trace):
            if (
                assessment.name == OVERRIDE.name
                and _kind(assessment) == "feedback"
                and assessment.source.source_id != TRACE_VIEW
                and assessment.valid is not False
            ):
                mlflow.override_feedback(
                    trace_id=trace.info.trace_id,
                    assessment_id=assessment.assessment_id,
                    value=OVERRIDE.value,
                    rationale=OVERRIDE.rationale,
                    source=AssessmentSource(source_type="HUMAN", source_id=OVERRIDE.author),
                )
                print(_line("override", OVERRIDE, trace.info.trace_id))
                print(
                    f"         of {assessment.assessment_id}, left by "
                    f"{assessment.source.source_id}: now invalid"
                )
                return
    print(
        f"nothing to override: no valid {OVERRIDE.name} feedback on {OVERRIDE.document} "
        "left under a name other than User"
    )


def reject(client: MlflowClient, experiment: str) -> None:
    for document, name, value in REJECTED:
        for trace in _traces(client, experiment, document):
            for assessment in _human(trace):
                if (
                    _kind(assessment) == "expectation"
                    and assessment.name == name
                    and (value is None or _value(assessment) == value)
                ):
                    mlflow.delete_assessment(
                        trace_id=trace.info.trace_id, assessment_id=assessment.assessment_id
                    )
                    print(
                        f"deleted  {document}  expectation {name:<13}"
                        f"{_shown(_value(assessment)):<16}{trace.info.trace_id}"
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("uri", nargs="?", default="http://127.0.0.1:5114")
    what = parser.add_mutually_exclusive_group()
    what.add_argument("--override", action="store_true", help="j.okafor overrides s.brunner")
    what.add_argument("--reject", action="store_true", help="delete the rejected expectations")
    args = parser.parse_args()

    # log_feedback and its siblings read the tracking URI MLflow was pointed at,
    # not a client's.
    mlflow.set_tracking_uri(args.uri)
    client = MlflowClient(tracking_uri=args.uri)
    found = client.get_experiment_by_name(EXPERIMENT)
    if found is None:
        raise SystemExit(f"no experiment {EXPERIMENT} on {args.uri}: run the pipeline first")

    if args.override:
        override(client, found.experiment_id)
    elif args.reject:
        reject(client, found.experiment_id)
    else:
        show_queue(client, found.experiment_id)
        first_pass(client, found.experiment_id)


if __name__ == "__main__":
    main()
