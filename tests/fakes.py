"""Test doubles.

`dossier` has no LangChain, so there is no `FakeListChatModel` to borrow. The
fake below implements the same shape the production code will take a model
client in as -- and, critically, it **counts calls**.

Counting is not a nicety. R2.5, R4.6, R5.5 and R5.7 are all claims about how many
calls happened, not about what came back. A fake that only returns canned text
cannot prove any of them.
"""

from __future__ import annotations

import inspect
import json
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from dossier.domain.datasets import PublishedDataset
from dossier.domain.ports import AttachmentRef, ItemRef, RawItem
from dossier.domain.versions import PublishedVersion


class FakeModelClientError(AssertionError):
    """Raised when a test asks the fake for more responses than it was given.

    An AssertionError rather than a plain exception: running out of scripted
    responses means the code under test made a call the test did not expect,
    which is a finding, not an infrastructure problem.
    """


@dataclass
class FakeModelClient:
    """A model client that returns canned responses and remembers every call.

    Responses are consumed in order. `model_id` is recorded on every call so a
    test can assert which pin was used without reaching into production code.
    """

    responses: list[str] = field(default_factory=list)
    model_id: str = "anthropic:claude-sonnet-4-5-20250929"
    calls: list[dict[str, object]] = field(default_factory=list)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "schema": schema,
                "model_id": self.model_id,
                # Recorded, because several rules are claims about which picture
                # a call was shown -- not only how many calls there were (R3.12).
                "parts": tuple(parts),
            }
        )
        if not self.responses:
            raise FakeModelClientError(
                f"call {self.call_count} was made with no scripted response left. "
                "Either the code under test called the model more often than the "
                "test expected, or the script is short."
            )
        return self.responses.pop(0)


class NoModelClient:
    """A client that fails on any call at all.

    For the rules that say *zero* calls -- `--plan` (R4.6), a full cache hit
    (R5.5), config loading (R3.8). Asserting `call_count == 0` proves the same
    thing, but this fails at the call site, which is where the answer is.
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        raise FakeModelClientError(
            "a model call was made where the rule under test permits none"
        )


class Gate:
    """Holds each model call until enough are in flight together (R9.19).

    It **counts how many calls were in flight at once**, as `FakeModelClient`
    counts calls: R9.19 is a claim about that number, and timing alone cannot
    prove it -- three calls that happened to arrive quickly would look
    concurrent and prove nothing.

    The gate opens once `meet` calls are in flight together, or every one of
    the `expected` documents not yet answered is, so the last of an uneven batch
    is not kept waiting for company that is not coming. Once open it stays
    open, and `order`, if given, is the order answers leave in. A run asking one
    at a time never opens a gate set above 1: each call waits out `patience`
    and passes anyway, so a red test fails on what was counted rather than
    hanging. `hold` keeps a call in flight briefly after the gate, so calls
    that do overlap are seen to.
    """

    def __init__(
        self,
        *,
        expected: int,
        meet: int = 1,
        order: Sequence[str] = (),
        patience: float = 2.0,
        hold: float = 0.05,
    ) -> None:
        self.expected = expected
        self.meet = meet
        self.order = tuple(order)
        self.patience = patience
        self.hold = hold
        self.asked: list[str] = []
        self.most_at_once = 0
        self._in_flight = 0
        self._answered: list[str] = []
        self._open = False
        self._condition = threading.Condition()

    def through(self, document: str) -> None:
        """Wait at the gate as a call about `document`, then leave it."""
        with self._condition:
            self.asked.append(document)
            self._in_flight += 1
            self.most_at_once = max(self.most_at_once, self._in_flight)
            if self._in_flight >= min(self.meet, self.expected - len(self._answered)):
                self._open = True
            self._condition.notify_all()
            self._condition.wait_for(
                lambda: self._open and self._turn(document), timeout=self.patience
            )
        time.sleep(self.hold)
        with self._condition:
            self._in_flight -= 1
            self._answered.append(document)
            self._condition.notify_all()

    def _turn(self, document: str) -> bool:
        return not self.order or self.order[len(self._answered)] == document


class FakeTrackerError(AssertionError):
    """Something was recorded out of order -- to a run or trace never started.

    An AssertionError, like `FakeModelClientError`: recording into nothing is
    a finding about the code under test, not an infrastructure problem.
    """


@dataclass
class FakeTrace:
    """One (step, document), as a tracker was told about it (spec 011)."""

    name: str
    tags: dict[str, str]
    spans: list[dict[str, object]] = field(default_factory=list)
    # The verdicts recorded on this trace (R11.16). A list, not a flag: rows 3
    # and 5 are both claims about how many there are.
    assessments: list[dict[str, object]] = field(default_factory=list)
    status: str | None = None
    error: str | None = None
    # What it was opened and closed with: the Request and Response the trace
    # list shows (R15.1). `None` for a trace given neither.
    inputs: dict[str, object] | None = None
    outputs: object = None


@dataclass
class FakeRun:
    """One MLflow run, as a tracker was told about it."""

    experiment: str
    name: str
    tags: dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    # The evaluation datasets this run was measured against (R11.7). A list, not
    # a flag: R11.7 rows 3 and 4 are both claims that there is exactly none.
    inputs: list[dict[str, str]] = field(default_factory=list)
    traces: list[FakeTrace] = field(default_factory=list)
    # The pipeline versions this run produced and the ones it scored
    # (R13.2). Two lists rather than one with a direction on it, because
    # a fake that stored both the same way could not fail when a run
    # claimed to have produced the version it only measured.
    produced: list[str] = field(default_factory=list)
    scored: list[str] = field(default_factory=list)
    # The figures recorded against a version rather than against this run
    # (R13.3), by version id.
    version_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    status: str | None = None


class FakeTracker:
    """A tracker that records what it is told and sends it nowhere.

    It **counts runs, traces and spans**, as `FakeModelClient` counts calls:
    R11.1 and R11.2 are claims about how many were recorded, and a tracker that
    only accepted calls could prove neither (spec 010). Every method returns
    `None` -- the port reads nothing back from a server, so nothing a tracker
    holds can reach a key, a manifest or a score (R0.10 row 5).

    A trace is current in the thread that opened it, as the port promises
    (R11.21): a fake holding one current trace for the process could not fail
    when a run's workers sent their spans to each other's traces.
    """

    def __init__(self) -> None:
        self.runs: list[FakeRun] = []
        # The trace each thread has open (R11.21), and a lock for the list
        # every thread's trace joins.
        self._open = threading.local()
        self._opening = threading.Lock()
        # (prompt name, version) per link, in the order the run made them.
        # A list rather than a set: R14.7 is a claim about which versions
        # were linked, and a duplicate would be a defect worth seeing.
        self.links: list[tuple[str, int]] = []
        # (version id, prompt name, prompt version): what a pipeline version is
        # made of, kept on the tracker because MLflow keeps it on the model (R14.12).
        self.version_links: list[tuple[str, str, int]] = []

    @property
    def traces(self) -> list[FakeTrace]:
        return [trace for run in self.runs for trace in run.traces]

    @property
    def spans(self) -> list[dict[str, object]]:
        return [span for trace in self.traces for span in trace.spans]

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None:
        self.runs.append(FakeRun(experiment=experiment, name=name, tags=dict(tags)))

    def rendered_prompt(self, *, name: str, version: int) -> None:
        self.links.append((name, version))

    def log_params(self, params: Mapping[str, str]) -> None:
        self._run.params.update(params)

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        self._run.metrics.update(metrics)

    def log_artifact(self, name: str, content: bytes) -> None:
        self._run.artifacts[name] = content

    def log_dataset(self, *, name: str, dataset_id: str, digest: str) -> None:
        self._run.inputs.append({"name": name, "dataset_id": dataset_id, "digest": digest})

    def produced_version(self, version_id: str) -> None:
        self._run.produced.append(version_id)

    def scored_version(self, version_id: str) -> None:
        self._run.scored.append(version_id)

    def version_prompt(self, *, version_id: str, name: str, version: int) -> None:
        # Only from inside a run, as a real one is sent: the tracker's client
        # exists once a run is open (FakeTrackerError otherwise).
        _ = self._run
        self.version_links.append((version_id, name, version))

    def log_version_metrics(self, *, version_id: str, metrics: Mapping[str, float]) -> None:
        self._run.version_metrics.setdefault(version_id, {}).update(metrics)

    def describe(self, text: str) -> None:
        # Stored as the tag MLflow renders as Description, rather than as a field
        # of its own: R10.12 is the claim that it goes *there*, and a fake that
        # kept it somewhere else could not fail when the tracker stopped.
        self._run.tags["mlflow.note.content"] = text

    def start_trace(
        self,
        *,
        name: str,
        tags: Mapping[str, str],
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        trace = FakeTrace(
            name=name, tags=dict(tags), inputs=None if inputs is None else dict(inputs)
        )
        with self._opening:
            self._run.traces.append(trace)
        self._open.trace = trace

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None:
        self._trace.spans.append({"kind": kind, "name": name, **attributes})

    def assess(self, *, name: str, value: bool, rationale: str, source: str) -> None:
        self._trace.assessments.append(
            {"name": name, "value": value, "rationale": rationale, "source": source}
        )

    def end_trace(
        self, *, status: str, error: str | None = None, outputs: object = None
    ) -> None:
        self._trace.status = status
        self._trace.error = error
        self._trace.outputs = outputs

    def end_run(self, *, status: str) -> None:
        # The statuses MLflow's `RunStatus.from_string` accepts. A run and a trace
        # have different vocabularies -- a trace ends `OK` or `ERROR` -- and
        # passing a trace's to a run raises against a real server while a fake
        # that stored any string at all said nothing (R10.6 is about records that
        # are lost, not records that were never valid).
        if status not in ("RUNNING", "SCHEDULED", "FINISHED", "FAILED", "KILLED"):
            raise FakeTrackerError(
                f"{status!r} is not an MLflow run status; a run ends FINISHED or FAILED"
            )
        self._run.status = status

    @property
    def _run(self) -> FakeRun:
        if not self.runs:
            raise FakeTrackerError("recorded to an MLflow run that was never started")
        return self.runs[-1]

    @property
    def _trace(self) -> FakeTrace:
        # The one this thread opened last, in the run now open: a span from a
        # thread that opened none, or recorded into a run it was not opened in,
        # is a defect in the caller and said as one.
        trace = getattr(self._open, "trace", None)
        if trace is None or not any(held is trace for held in self._run.traces):
            raise FakeTrackerError("recorded to a trace that was never started")
        return trace


@dataclass
class FakeDataset:
    """One MLflow evaluation dataset, as a registry was told to publish it (spec 012).

    Both identities here are modelled on what a real server actually does, because
    the first version of this fake invented friendlier ones and R12.3 passed
    against a property MLflow does not have.
    """

    name: str
    experiments: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    # Keyed the way MLflow keys a record: the SHA-256 of its `inputs`, which
    # `upsert_dataset_records` computes over `json.dumps(inputs, sort_keys=True)`.
    # Keying this fake any other way would let R12.3 pass here and fail against a
    # real server, which is the one thing a fake of a merge must not do.
    records: dict[str, dict] = field(default_factory=dict)
    # How many times this dataset has been *written to*. MLflow's digest is
    # `sha256("<name>:<last_update_time>")` -- see `_compute_dataset_digest` in
    # `sqlalchemy_store.py` -- so it is a marker for a write and says nothing
    # about content: two identical merges give two different digests. A clock
    # stands in for the clock here; what matters is that a write moves it and
    # nothing else does.
    writes: int = 0

    @property
    def digest(self) -> str:
        """MLflow's digest, which moves on a write and not on a change (R12.3).

        Deliberately *not* a hash of the records. A fake that made this a content
        hash would report an unchanged digest for a publish that sent the same
        records again, which is exactly the bug a live publish found.
        """
        return sha256(f"{self.name}:{self.writes}".encode()).hexdigest()[:8]


class FakeDatasetRegistry:
    """A dataset registry that holds what it is told and sends it nowhere.

    Unlike `FakeTracker`, whose every method returns `None`, this one **returns**
    a dataset id, a digest and a record count -- which is the whole reason spec
    012 gives it a port of its own rather than a method on `Tracker` (R0.10).
    What a command may do with what comes back is R12.4: a tag, a printed line,
    and nothing on disk.

    It counts publishes as `FakeTracker` counts runs: R12.3 and R12.6 are claims
    about how many datasets were created, not about what came back from creating
    them.
    """

    def __init__(self) -> None:
        self.datasets: dict[str, FakeDataset] = {}
        self.created: list[str] = []
        self.publishes: list[dict] = []

    def publish(
        self,
        *,
        name: str,
        experiment: str,
        records: Sequence[Mapping[str, object]],
        tags: Mapping[str, str],
    ) -> PublishedDataset:
        self.publishes.append(
            {"name": name, "experiment": experiment, "records": list(records)}
        )
        dataset = self.datasets.get(name)
        created = dataset is None
        if dataset is None:
            dataset = FakeDataset(name=name)
            self.datasets[name] = dataset
            self.created.append(name)
            dataset.writes += 1
        if experiment not in dataset.experiments:
            dataset.experiments.append(experiment)
            dataset.writes += 1
        if any(dataset.tags.get(key) != value for key, value in tags.items()):
            dataset.tags.update(tags)
            dataset.writes += 1
        if records:
            # A merge is a write whether or not it changes anything, which is why
            # `publish_gold` does not call one for a gold set that has not moved.
            dataset.writes += 1
        added = 0
        for record in records:
            key = sha256(
                json.dumps(record.get("inputs", {}), sort_keys=True).encode("utf-8")
            ).hexdigest()
            if key not in dataset.records:
                added += 1
            # Merged, not replaced, as `upsert_dataset_records` merges: a record
            # already there keeps what this publish does not carry.
            held = dataset.records.setdefault(key, {})
            for name_of, value in record.items():
                if name_of == "tags" and isinstance(value, Mapping):
                    held.setdefault("tags", {}).update(value)
                else:
                    held[name_of] = value
        return PublishedDataset(
            dataset_id=self._id(name),
            name=name,
            digest=dataset.digest,
            records=len(dataset.records),
            added=added,
            created=created,
            tags=dict(dataset.tags),
        )

    def find(self, name: str) -> PublishedDataset | None:
        dataset = self.datasets.get(name)
        if dataset is None:
            return None
        return PublishedDataset(
            dataset_id=self._id(name),
            name=name,
            digest=dataset.digest,
            records=len(dataset.records),
            added=0,
            created=False,
            tags=dict(dataset.tags),
        )

    @staticmethod
    def _id(name: str) -> str:
        """A stable id, shaped like MLflow's `d-<32 hex>`."""
        return f"d-{sha256(name.encode('utf-8')).hexdigest()[:32]}"


class VersionedFolderConnector:
    """A local directory that also carries a per-item version marker.

    Confluence's shape without Confluence's network: `list` reports a
    `remote_version` it did not invent, so R2.1's "trust the marker" branch is
    reachable from an acceptance test. The shipped folder connector cannot stand
    in for this -- its markers are `None` by design (R1.5), which is precisely
    the distinction R2.15 exists to draw.

    The markers live in a JSON file the test owns, so a test can move `OPS-114`
    from `v37` to `v38` (the source changed) or edit a payload while leaving the
    manifest alone (the source changed behind its own back) and get two
    different, meaningful answers.

    **It counts fetches.** R2.15 is a claim about how many payloads were read,
    not about what came back, so a fake that only returns bytes cannot prove it.
    """

    lists_everything = False

    media_type = "text/markdown"

    def __init__(self, root: Path, manifest: Path) -> None:
        self._root = Path(root)
        self._manifest = Path(manifest)
        self.fetched: list[str] = []

    @property
    def fetch_count(self) -> int:
        return len(self.fetched)

    def _versions(self) -> dict[str, str]:
        """Read the manifest on every call rather than caching it.

        A test edits it between the two runs; a connector holding the first
        run's answer would make the second run pass for the wrong reason.
        """
        return json.loads(self._manifest.read_text(encoding="utf-8"))

    def list(self, since: datetime | None = None) -> Iterator[ItemRef]:
        """Every page, in key order, each with the marker the source vouches for.

        `since` is accepted and ignored: over-returning is always legal, and
        R2.15 is about what happens to the items that *are* listed (R1.4).
        """
        versions = self._versions()
        for key in sorted(versions):
            yield ItemRef(key=key, remote_version=versions[key], updated_at=None)

    def fetch(self, key: str) -> RawItem:
        self.fetched.append(key)
        payload = (self._root / f"{key}.md").read_bytes()
        return RawItem(
            key=key,
            payload=payload,
            media_type=self.media_type,
            remote_version=self._versions()[key],
        )

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        return iter(())


class _StubEntryPoint:
    """An entry point that resolves to an object already in memory.

    `importlib.metadata.EntryPoint` loads by import string, which a connector
    built inside a test does not have. This carries the factory itself and
    otherwise looks the same to the registry.
    """

    def __init__(self, name: str, group: str, factory) -> None:
        self.name = name
        self.group = group
        self._factory = factory

    def load(self):
        return self._factory


def register_provider(
    monkeypatch, name: str, factory, *, default_url: str | None = None
) -> None:
    """Make a model provider available the way an installed package would (R9.1).

    Replaces any installed provider of the same name, so the stub is the one a
    run resolves: a shipped provider is a placeholder until its client lands.
    Registering rather than patching `build_model_client` matters for the same
    reason it does for connectors -- it exercises the resolution path the rule
    under test actually runs through.

    `default_url` is where the provider is reached when its variable is unset,
    as spec 009's table states one for each provider. `None` means it has none,
    which is `hf`'s row.
    """
    import dossier.infrastructure.models.registry as registry

    factory.default_url = default_url
    stub = _StubEntryPoint(name, registry.ENTRY_POINT_GROUP, factory)
    # Whatever the registry sees now, which may already carry another stub: two
    # providers registered by one test both stay registered.
    current = registry.entry_points

    def with_stub(group: str):
        found = list(current(group=group))
        if group != registry.ENTRY_POINT_GROUP:
            return found
        return [point for point in found if point.name != name] + [stub]

    monkeypatch.setattr(registry, "entry_points", with_stub)


def register_connector(monkeypatch, type_name: str, factory, *, keys=None) -> None:
    """Make a source type available the way an installed package would (R1.7).

    The installed entry points are kept and the stub is appended, so a test using
    a fake source type can still sync a `folder` one alongside it. Registering
    rather than patching `build_connector` matters: it exercises the resolution
    path the rule under test actually runs through.

    `keys` is the model of the keys its sources take beyond the shared ones, as
    a real connector declares them (R1.10). Without it, the stub takes none.
    """
    from importlib.metadata import entry_points

    import dossier.infrastructure.connectors.registry as registry

    if keys is not None:
        factory.keys = keys

    takes_credential = "credential" in inspect.signature(factory).parameters

    def built(config, *, workspace, credential=None):
        """The factory a test gave, taking the argument `build_connector` passes.

        Absorbed here so that a stub can stay the two-line lambda it wants to be:
        a credential is resolved by the composition root and handed to every
        connector (R1.8), and most fake sources need none. One that declares
        the parameter is handed it, as a real factory is.
        """
        if takes_credential:
            return factory(config, workspace=workspace, credential=credential)
        return factory(config, workspace=workspace)

    built.keys = getattr(factory, "keys", None)
    stub = _StubEntryPoint(type_name, registry.ENTRY_POINT_GROUP, built)

    def with_stub(group: str):
        found = list(entry_points(group=group))
        if group != registry.ENTRY_POINT_GROUP:
            return found
        # The stub comes first, and shadows an installed connector of the same
        # name, exactly as `register_provider` replaces a provider. Appending
        # instead would leave a test that says "make `jira` available" quietly
        # exercising the shipped Jira connector, which is not what it asked for.
        return [stub] + [point for point in found if point.name != type_name]

    monkeypatch.setattr(registry, "entry_points", with_stub)


@dataclass
class FakePrompt:
    """One prompt in the registry, and every version it has held.

    A version is append-only here as it is in MLflow: `register_prompt` creates
    one unconditionally, including for text identical to the version above it,
    which is the behaviour R14.4 exists to work around. A fake that returned the
    existing version for identical text would let R14.4 pass here and fail
    against a real server.
    """

    name: str
    versions: list[dict] = field(default_factory=list)

    @property
    def version(self) -> int:
        return len(self.versions)

    @property
    def latest_hash(self) -> str:
        return self.versions[-1]["tags"].get("dossier.prompt_hash", "") if self.versions else ""


class FakePromptRegistry:
    """A prompt registry that holds what it is told and sends it nowhere.

    A third port beside `FakeDatasetRegistry`, for the reason spec 014 gives it
    one: publishing **returns** a version number, which `Tracker`'s contract
    forbids (R0.10). What a command may do with what comes back is R14.5 -- the
    terminal line, and nothing on disk.

    It counts, because R14.1 and R14.4 are claims about how many prompts and
    versions exist afterwards, not about what came back from making them.
    """

    def __init__(self) -> None:
        self.prompts: dict[str, FakePrompt] = {}
        self.publishes: list[dict] = []
        self.reads: list[str] = []

    def publish(
        self,
        *,
        name: str,
        template: str,
        tags: Mapping[str, str],
        commit_message: str = "",
    ):
        from dossier.domain.prompts import PublishedPrompt

        self.publishes.append({"name": name, "template": template, "tags": dict(tags)})
        prompt = self.prompts.setdefault(name, FakePrompt(name=name))
        prompt.versions.append(
            {"template": template, "tags": dict(tags), "commit_message": commit_message}
        )
        return PublishedPrompt(
            name=name,
            version=prompt.version,
            prompt_hash=tags.get("dossier.prompt_hash", ""),
            created=True,
        )

    def latest(self, name: str):
        """The newest version of `name`, or `None`. The one read R14.5 row 4 permits.

        Recorded, so a test can assert that a publish asked before it wrote and
        that nothing on the run path ever asks at all.
        """
        from dossier.domain.prompts import PublishedPrompt

        self.reads.append(name)
        prompt = self.prompts.get(name)
        if prompt is None:
            return None
        return PublishedPrompt(
            name=name,
            version=prompt.version,
            prompt_hash=prompt.latest_hash,
            created=False,
        )

    def find(self, name: str, prompt_hash: str):
        """The version carrying `prompt_hash`, oldest first, or `None` (R14.7).

        Oldest first because a hash reverted to is the same hash: republishing
        a prompt back to text it already held leaves two versions tagged
        identically, and the first is the one a person diffing the history
        would call the original.
        """
        from dossier.domain.prompts import PublishedPrompt

        self.reads.append(name)
        prompt = self.prompts.get(name)
        if prompt is None:
            return None
        for number, held in enumerate(prompt.versions, start=1):
            if held["tags"].get("dossier.prompt_hash") == prompt_hash:
                return PublishedPrompt(
                    name=name, version=number, prompt_hash=prompt_hash, created=False
                )
        return None


@dataclass
class FakeVersion:
    """One logged model, as a registry was told about it."""

    version_id: str
    name: str
    experiment: str
    params: dict[str, str]
    tags: dict[str, str]
    # A version left pending is a record saying something is still being
    # written, which is untrue the moment the run that made it has ended
    # (R13.1). A field rather than an assumption, so a registry that forgot to
    # finalise fails a test.
    ready: bool = False


class FakeVersionRegistry:
    """A version registry that holds what it is told and sends it nowhere.

    Like `FakeDatasetRegistry` and unlike `FakeTracker`, it **returns** -- a
    version id, which is the whole reason spec 013 gives it a port of its own
    (R0.10). What a command may do with what comes back is R13.4.

    It finds before it creates, because that is the behaviour under test: MLflow
    makes a new logged model every time it is asked by name, so `registrations`
    counting higher than `versions` is exactly what R13.1 row 2 asserts.
    """

    def __init__(self) -> None:
        self.versions: list[FakeVersion] = []
        self.registrations: list[dict] = []

    def register(self, *, record, experiment: str) -> PublishedVersion:
        from dossier.domain.versions import HASH_TAG, PIPELINE_TAG

        self.registrations.append(
            {"name": record.name, "experiment": experiment, "tags": dict(record.tags)}
        )
        wanted = (record.tags[PIPELINE_TAG], record.tags[HASH_TAG])
        for held in self.versions:
            if (held.tags[PIPELINE_TAG], held.tags[HASH_TAG]) == wanted:
                return PublishedVersion(
                    version_id=held.version_id,
                    name=held.name,
                    pipeline_hash=held.tags[HASH_TAG],
                    created=False,
                    params=dict(held.params),
                )
        made = FakeVersion(
            # MLflow's shape, so a test asserting on what is printed sees what a
            # person would (`_fixtures.md`).
            version_id=f"m-{len(self.versions):032x}",
            name=record.name,
            experiment=experiment,
            params=dict(record.params),
            tags=dict(record.tags),
            ready=True,
        )
        self.versions.append(made)
        return PublishedVersion(
            version_id=made.version_id,
            name=made.name,
            pipeline_hash=made.tags[HASH_TAG],
            created=True,
            params=dict(made.params),
        )
