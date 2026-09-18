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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dossier.domain.ports import AttachmentRef, ItemRef, RawItem


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

    def complete(self, prompt: str, *, schema: dict | None = None) -> str:
        raise FakeModelClientError(
            "a model call was made where the rule under test permits none"
        )


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
    status: str | None = None
    error: str | None = None


@dataclass
class FakeRun:
    """One MLflow run, as a tracker was told about it."""

    experiment: str
    name: str
    tags: dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    traces: list[FakeTrace] = field(default_factory=list)
    status: str | None = None


class FakeTracker:
    """A tracker that records what it is told and sends it nowhere.

    It **counts runs, traces and spans**, as `FakeModelClient` counts calls:
    R11.1 and R11.2 are claims about how many were recorded, and a tracker that
    only accepted calls could prove neither (spec 010). Every method returns
    `None` -- the port reads nothing back from a server, so nothing a tracker
    holds can reach a key, a manifest or a score (R0.10 row 5).
    """

    def __init__(self) -> None:
        self.runs: list[FakeRun] = []

    @property
    def traces(self) -> list[FakeTrace]:
        return [trace for run in self.runs for trace in run.traces]

    @property
    def spans(self) -> list[dict[str, object]]:
        return [span for trace in self.traces for span in trace.spans]

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None:
        self.runs.append(FakeRun(experiment=experiment, name=name, tags=dict(tags)))

    def log_params(self, params: Mapping[str, str]) -> None:
        self._run.params.update(params)

    def log_metrics(self, metrics: Mapping[str, float]) -> None:
        self._run.metrics.update(metrics)

    def log_artifact(self, name: str, content: bytes) -> None:
        self._run.artifacts[name] = content

    def start_trace(self, *, name: str, tags: Mapping[str, str]) -> None:
        self._run.traces.append(FakeTrace(name=name, tags=dict(tags)))

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None:
        self._trace.spans.append({"kind": kind, "name": name, **attributes})

    def end_trace(self, *, status: str, error: str | None = None) -> None:
        self._trace.status = status
        self._trace.error = error

    def end_run(self, *, status: str) -> None:
        self._run.status = status

    @property
    def _run(self) -> FakeRun:
        if not self.runs:
            raise FakeTrackerError("recorded to an MLflow run that was never started")
        return self.runs[-1]

    @property
    def _trace(self) -> FakeTrace:
        if not self._run.traces:
            raise FakeTrackerError("recorded to a trace that was never started")
        return self._run.traces[-1]


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
