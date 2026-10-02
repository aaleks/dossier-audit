"""The interfaces the outside world is reached through (spec 001).

Protocols and value objects only -- pure types, no behaviour, no IO. They live in
`domain/` so that `application/` can depend on them without depending on any
implementation, which is what lets every use case run against a fake.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from dossier.domain.chunks import Chunk
from dossier.domain.datasets import PublishedDataset
from dossier.domain.index import IndexedChunk, IndexedDocument
from dossier.domain.prompts import PublishedPrompt
from dossier.domain.review import Verdict
from dossier.domain.search import Lists
from dossier.domain.versions import PublishedVersion, VersionRecord


class ItemRef(BaseModel):
    """One item as it appears in a listing."""

    model_config = ConfigDict(frozen=True)

    key: str
    remote_version: str | None = None
    updated_at: datetime | None = None


class RawItem(BaseModel):
    """One item's payload, exactly as received (R1.43)."""

    model_config = ConfigDict(frozen=True)

    key: str
    payload: bytes
    media_type: str
    remote_version: str | None = None


class AttachmentRef(BaseModel):
    """A file carried by an item, addressed and versioned independently (R1.6)."""

    model_config = ConfigDict(frozen=True)

    key: str
    item_key: str
    remote_version: str | None = None


@runtime_checkable
class Connector(Protocol):
    """The three questions every source type answers.

    Implementations live in `dossier.infrastructure.connectors`, the package
    left of the hash boundary that fetches a source (R0.19), and are discovered
    through the `dossier.connectors` entry point group rather than named
    anywhere in the core package (R1.7).
    """

    # Whether `list` ignores `since` and returns everything on every call. Sync
    # computes tombstones only against a listing it knows to be complete, and
    # it can see that for itself when it asked with `since=None`; this is the
    # case it cannot see. Without it, a folder -- which always returns
    # everything -- was believed only on its first sync, and a file deleted
    # from it stayed `active` for ever (R1.11, R2.21).
    lists_everything: bool

    # A connector may also declare `fetch_asks: str`, what its fetch asks for
    # beyond an item's address, which joins the source configuration hash
    # (R2.26). Not a member here: a connector that asks for nothing more need
    # not say so, and sync reads it with `getattr` and a default of "".

    def list(self, since: datetime | None) -> Iterator[ItemRef]:
        """Every item currently in scope.

        When `since` is given the connector MAY restrict the result to items
        changed at or after it. Returning more than asked for is always allowed;
        returning less is a defect that presents as a document silently going
        stale (R1.4).
        """
        ...

    def fetch(self, key: str) -> RawItem:
        """The full payload of one item, byte-for-byte as received (R1.43)."""
        ...

    def attachments(self, key: str) -> Iterator[AttachmentRef]:
        """Files attached to the item, each independently addressable (R1.6)."""
        ...


class ImagePart(BaseModel):
    """Bytes a stage hands a model, with what they are (R9.16).

    Declared here beside the port rather than in the provider that sends it,
    because `application` builds one and may import nothing but `domain`. What a
    provider does with it -- a data URI, a base64 source block, an array beside
    the message -- differs between all three and is the provider's business.

    Frozen, because a part is an input to a cache key by content: something that
    could be edited after the key was computed would make the key a lie.
    """

    model_config = ConfigDict(frozen=True)

    media_type: str
    data: bytes


class Reply(str):
    """A model's answer: the text, and what its provider counted it cost (R9.18).

    A `str`, and that is the design rather than a shortcut. Every caller that
    reads an answer reads text -- validates it, caches it, hands it to the next
    prompt -- and reads this one unchanged. A client that reports nothing, a
    test's fake among them, returns plain text and is still a `ModelClient`.

    The counts are `None` when the provider did not give them. Never 0: a
    passthrough that strips `usage` has not reported a free completion.

    Nothing here enters a key. Tokens are what an answer cost, not what it was
    asked (R0.5).
    """

    input_tokens: int | None
    output_tokens: int | None

    def __new__(
        cls, text: str, *, input_tokens: int | None = None, output_tokens: int | None = None
    ) -> Reply:
        reply = super().__new__(cls, text)
        reply.input_tokens = input_tokens
        reply.output_tokens = output_tokens
        return reply


@runtime_checkable
class ModelClient(Protocol):
    """How a stage reaches a model.

    Declared here so that `application/` can run a stage without importing any
    vendor SDK, and so the default test suite can hand it a fake that counts
    calls -- R4.6, R5.5 and R5.10 are all claims about how many calls happened.

    `model_id` is on the client rather than passed per call because it is part of
    the key of every stage it answers (R5.13) and part of every provenance record
    (R0.3): a score without the model that produced it is not reproducible.
    """

    model_id: str

    def complete(
        self,
        prompt: str,
        *,
        schema: dict | None = None,
        parts: Sequence[ImagePart] = (),
    ) -> str:
        """One completion, returned as text for the caller to validate.

        A client whose provider says what the answer cost returns a `Reply`,
        which is text carrying the counts (R9.18); one that does not returns
        plain `str`, and reads as having reported nothing.

        `parts` are images the prompt is about, in the order the caller means
        them -- page order, for a document. A call with none sends exactly what
        it sent before parts existed, so no cache key moves (R9.16 row 5).
        """
        ...


@runtime_checkable
class DatasetRegistry(Protocol):
    """Where a gold set is published as an MLflow evaluation dataset (spec 012).

    A second port beside `Tracker`, and the reason is the one thing it does that
    `Tracker` does not: it **returns**. A dataset id, a digest and a record count
    come back from a server, which is exactly what `Tracker`'s contract forbids
    (R15.5 row 2). R0.19 lets tracking read back only what a spec fences, and
    this port is where spec 012 fences it. Splitting them keeps the stronger
    promise intact where it matters.

    What comes back may reach an MLflow tag and a line in the terminal, and
    nothing else: no cache key, no manifest, no score, no file under `runs/` or
    `.dossier/` (R12.4 row 3). A dataset is a projection of `gold/`, read by a
    person; `dossier` only asks whether it still matches what was scored
    (R11.7).
    """

    def publish(
        self,
        *,
        name: str,
        experiment: str,
        records: Sequence[Mapping[str, object]],
        tags: Mapping[str, str],
    ) -> PublishedDataset:
        """Create the dataset if it is not there, merge `records` into it, tag it.

        Merged, never replaced: a record already there is updated in place on the
        document its `inputs` name, so publishing the same gold set twice is a
        no-op (R12.3). The dataset belongs to `experiment` in addition to any it
        already belongs to, because one gold set can serve several pipelines
        (R12.6).
        """
        ...

    def find(self, name: str) -> PublishedDataset | None:
        """The dataset published under `name`, or `None` if there is none.

        Read by `dossier eval` to say whether what it scored is what was
        published (R11.7), and by nothing that computes a figure.
        """
        ...


@runtime_checkable
class ReviewSource(Protocol):
    """Where the verdicts reviewers left on a pipeline's traces are read back from (spec 015).

    The one port through which `dossier` reads what a person said in MLflow, and
    a port of its own for the reason `DatasetRegistry` is: it **returns** what it
    read, which a `Tracker` never does (R15.5 row 2). Only `dossier review
    pull` builds one, and what it returns reaches the files under `review/` and
    nothing else -- no key, manifest, artifact or score (R15.5).
    """

    def human_verdicts(self, *, experiment: str) -> list[Verdict]:
        """Every valid verdict a person left on the traces of the runs in `experiment`.

        A verdict another reviewer overrode is not among them, nor the judge's
        verdicts: only what a person said, and still says (R15.3).
        """
        ...


class Tracker(Protocol):
    """Where a command's record is sent (spec 010, spec 011).

    Every method **sends and returns nothing** (R15.5 row 2). R0.19 lets
    tracking read back only what specs 012 to 015 fence, and each of those reads
    has a port of its own: `DatasetRegistry`, `VersionRegistry`,
    `PromptRegistry` and `ReviewSource`. This one only reports, so nothing
    MLflow holds can enter a key, a manifest or a score through it, and a run is
    reproducible whether tracking is on or off (R10.4). A method that returned
    something read from the server would be a way in that no spec fences.

    Declared here so that `application/` records without importing MLflow, and
    so the default suite can hand it a `FakeTracker` that counts runs, traces and
    spans -- R11.1 and R11.2 are claims about how many were recorded.

    A run holds traces; a trace is one (step, document), the unit of a cache key
    (spec 011), and holds spans.

    A trace is current in the thread that opened it: `span`, `assess` and
    `end_trace` are about the trace their own thread opened last. A run asking
    about several documents at once opens each one's trace on the worker that
    asks about it, and a tracker holding one current trace for the process
    would send every span to the last trace opened (R11.21).
    """

    def start_run(self, *, experiment: str, name: str, tags: Mapping[str, str]) -> None: ...

    def log_params(self, params: Mapping[str, str]) -> None: ...

    def log_metrics(self, metrics: Mapping[str, float]) -> None: ...

    def log_artifact(self, name: str, content: bytes) -> None: ...

    def log_dataset(self, *, name: str, dataset_id: str, digest: str) -> None:
        """Record that this run was measured against that evaluation dataset (R11.7).

        Sends and returns nothing, like every other method here. The dataset was
        found through `DatasetRegistry`, which is the port allowed to read; this
        one only says which one it was, so the run and the answers behind it are
        one click apart in the UI.
        """
        ...

    def describe(self, text: str) -> None:
        """Set this run's description, which MLflow shows first (R10.12, R11.12).

        A method of its own rather than a tag in `start_run`, because a
        description restates figures that do not exist when a run opens: an eval
        describes itself when it closes, with the accuracy it just printed.
        """
        ...

    def produced_version(self, version_id: str) -> None:
        """Record that this run built that pipeline version (R13.2 row 1).

        An output edge: the run made it. Sends and returns nothing, like every
        other method here -- the version was registered through
        `VersionRegistry`, which is the port allowed to read, and this one only
        says which way round the two are.
        """
        ...

    def scored_version(self, version_id: str) -> None:
        """Record that this run measured that pipeline version (R13.2 row 2).

        An input edge: an eval consumes a version, it does not make one. The
        same edge in both directions would make an eval look like it produced
        the pipeline it scored.
        """
        ...

    def rendered_prompt(self, *, name: str, version: int) -> None:
        """Record that this run rendered that prompt version (R14.7).

        The name and the version, not the words: the tracker says which entry
        in the registry produced this run, and a person follows the link to
        read it. Sends and returns nothing, like every other method here --
        finding the version is `PromptRegistry.find`'s job, and it is the port
        allowed to read (R14.5 row 5).
        """
        ...

    def version_prompt(self, *, version_id: str, name: str, version: int) -> None:
        """Record that pipeline version `version_id` is made of that prompt version (R14.12).

        The version a run built, by the id the version registry returned, and a
        prompt version found by the hash the run rendered -- so the link is a
        statement about what the version is made of. Sends and returns nothing,
        like `log_version_metrics`: the id arrives from `VersionRegistry`, the
        port allowed to return one (R0.19, R13.4).
        """
        ...

    def log_version_metrics(self, *, version_id: str, metrics: Mapping[str, float]) -> None:
        """Record this run's figures against that version too (R13.3).

        The same numbers `log_metrics` puts on the run. A metric on a run
        compares with other runs; a metric on a version compares with other
        versions, which is the comparison spec 013 exists for.
        """
        ...

    def start_trace(
        self,
        *,
        name: str,
        tags: Mapping[str, str],
        inputs: Mapping[str, object] | None = None,
    ) -> None:
        """Open a trace, with what it was asked about as its request (R15.1)."""
        ...

    def span(self, *, kind: str, name: str, attributes: Mapping[str, object]) -> None: ...

    def assess(self, *, name: str, value: bool, rationale: str, source: str) -> None:
        """Record a verdict `dossier` reached on the trace it is about (R11.16).

        A projection, one way only, as a published dataset is (R12.4): nothing
        MLflow holds about an assessment is ever read back, and no score, key or
        file is computed from one. `mlflow.genai.evaluate` is the thing this is
        not -- it would have MLflow arrive at a verdict of its own from the same
        material, which is the second way of computing spec 011 forbids.
        """
        ...

    def end_trace(
        self,
        *,
        status: str,
        error: str | None = None,
        outputs: object = None,
        tags: Mapping[str, str] | None = None,
    ) -> None:
        """Close the trace, with what it answered as its response (R15.1), and
        the tags only its end can know -- whether it belongs in the review
        queue (R15.2)."""
        ...

    def end_run(self, *, status: str) -> None: ...

    def use_experiment(self, experiment: str) -> None:
        """Record the traces that follow in `experiment`, under no run (R11.35).

        For a command that changes nothing, and so opens no run: a search.
        """
        ...

    def end_traces(self) -> None:
        """Close what `use_experiment` opened, looking for each trace as `end_run` does."""
        ...


@runtime_checkable
class Converter(Protocol):
    """Turning one snapshot into one artifact a stage can read (spec 008).

    The four identity attributes are not decoration. `media_type` and `kind` are
    the pair a converter is selected by (R8.3); `id` and `version` enter every
    convert key and every provenance record, so raising the version invalidates
    exactly the artifacts this converter produced and nothing else (R5.4, R8.2).

    The obligation on an author is precise and no test can enforce it: **raise
    `version` whenever output could change for the same input.** A converter that
    improves without doing so leaves a cache full of artifacts claiming to be
    something they are not, and nothing anywhere will notice.
    """

    id: str
    version: str
    media_type: str
    kind: str

    def convert(self, payload: bytes, options: Mapping[str, str]) -> bytes:
        """The artifact, as a pure function of `payload` and `options` (R8.1).

        Reads nothing else: no clock, no locale, no environment variable, no file
        outside its input, and no network (R0.19). `K_convert` claims the artifact
        is determined by the snapshot hash, this converter's id and version, and
        these options; a converter consulting anything else makes that key a lie
        and the cache serves text nothing can detect as stale.
        """
        ...


@runtime_checkable
class SnapshotReader(Protocol):
    """Reading back what the store holds, by content hash.

    Read-only on purpose. A use case that could write to the snapshot store
    could break R0.2 by accident, and no caller right of the hash boundary has
    any business storing a snapshot.
    """

    def get(self, digest: str) -> bytes:
        """The stored bytes, or `FileNotFoundError` naming the hash."""
        ...

    def exists(self, digest: str) -> bool:
        """Whether the store holds `digest`; a read, so a replay may ask (R4.7 row 4)."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Where a computed artifact is kept against the key that describes it.

    A cache and never a source of truth (R5.9): a miss is the normal case, so
    `get` answers `None` rather than raising, and nothing may treat what comes
    back as authority for anything except "this work was already done".
    """

    def get(self, key: str, *, require_record: bool = False) -> bytes | None:
        """The artifact, or `None`. With `require_record`, a hit needs its record.

        An artifact whose provenance record is missing is not a cache entry: the
        process was killed between the two writes, and nothing can say what
        produced those bytes (R0.3, R5.8).
        """
        ...

    def record(self, key: str) -> dict | None:
        """The provenance record beside the artifact at `key`, or `None`.

        Read so a run can put the record beside the copy a person opens
        (R0.11, R0.3) -- for a hit as for a miss, since a served artifact is
        still an output. Never read as authority for anything else.
        """
        ...

    def put(self, key: str, payload: bytes, *, record: dict | None = None) -> None: ...


class CollectableStore(ArtifactStore, Protocol):
    """An `ArtifactStore` that can say what it holds, for `dossier gc` (spec 016).

    Separate from `ArtifactStore`, which every stage is handed: nothing that
    computes an answer has any business listing what else is kept.
    """

    def all_keys(self) -> list[str]:
        """Every key holding an artifact, sorted."""
        ...

    def size(self, key: str) -> int:
        """The bytes the entry at `key` takes: its artifact and its record."""
        ...

    def delete(self, key: str) -> None:
        """Remove the entry at `key`, artifact and record."""
        ...


@runtime_checkable
class SnapshotWriter(Protocol):
    """Storing and reading back snapshots, for the one use case that stores them.

    Deliberately separate from `SnapshotReader`. Only `sync` writes snapshots;
    everything right of the hash boundary reads. Handing convert or run a type
    with `put` on it would be handing them a way to break R0.2 by accident.
    """

    def put(self, payload: bytes) -> str: ...

    def get(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


@runtime_checkable
class LedgerWriter(Protocol):
    """What `sync` needs of a ledger.

    Named so the seam is checkable rather than conventional: `sync_source` takes
    its store and its ledger as arguments and constructs neither, which is what
    lets the whole use case run against fakes -- and those two parameters were the
    ones with no type.
    """

    def rows(self, source_id: str) -> list: ...

    def row(self, source_id: str, key: str): ...

    def record(self, row) -> None: ...

    def touch(self, source_id: str, key: str, *, seen_at: datetime) -> None: ...

    def set_state(self, source_id: str, keys: Iterable[str], state) -> None: ...

    def set_watermark(self, source_id: str, when: datetime) -> None: ...

    def config_hash(self, source_id: str) -> str | None: ...

    def set_config_hash(self, source_id: str, value: str) -> None: ...

    def listing_hash(self, source_id: str) -> str | None: ...

    def set_listing_hash(self, source_id: str, value: str) -> None: ...

    def owed(self, source_id: str) -> list[tuple[str, str | None]]: ...

    def owe(
        self, source_id: str, key: str, *, item_key: str | None, at: datetime, error: str
    ) -> None: ...

    def settle(self, source_id: str, keys: Iterable[str]) -> None: ...


class PromptRegistry(Protocol):
    """Where a pipeline's prompts are published as versions (spec 014).

    A third port beside `DatasetRegistry`, for the reason spec 012 gave for the
    second: it **returns**. A version number comes back from a server, which
    `Tracker`'s contract forbids.

    There is no `load`. MLflow's prompt registry exists to be read from, and
    dossier declines that half of it: a prompt fetched at run time would be an
    input to a cache key that no checkout can reproduce (R0.4), a route into a
    run that no review passed through, and a network read on the replay path
    (R0.19). The prompt files in the pipeline's own directory stay the only
    source (R14.5).
    """

    def publish(
        self,
        *,
        name: str,
        template: str,
        tags: Mapping[str, str],
        commit_message: str = "",
    ) -> PublishedPrompt:
        """Register `template` under `name`, creating the prompt if it is new.

        MLflow versions unconditionally -- `register_prompt` creates a version
        even for text identical to the one above it -- so deciding *whether* to
        call this is the caller's, and R14.4 is that decision.
        """
        ...

    def latest(self, name: str) -> PublishedPrompt | None:
        """The newest version of `name`, or `None` if there is no such prompt.

        A read the one-way promise permits, because it decides a **write** and
        reaches no output (R14.5 row 4). `find` is the other.
        """
        ...

    def find(self, name: str, prompt_hash: str) -> PublishedPrompt | None:
        """The version of `name` tagged with `prompt_hash`, or `None`.

        By the hash rather than by recency, because a run links what it
        *rendered*: a prompt edited and republished since would otherwise
        attach its newest words to a run that never saw them (R14.7 row 1).

        Reads a version number and never a template -- `PublishedPrompt` has no
        field for one -- so the text a run renders still comes only from the
        file on disk (R14.5 row 5).
        """
        ...


class VersionRegistry(Protocol):
    """Where a pipeline version is registered as an MLflow logged model (spec 013).

    A third port, beside `Tracker` and `DatasetRegistry`, and for
    `DatasetRegistry`'s reason: registering a version **returns** an id, which
    `Tracker`'s contract forbids (R15.5 row 2) and R0.19 lets tracking read back
    only because spec 013 fences it.

    It matters more here than it did for datasets. A dataset is published by a
    command whose only output is the record; a version is registered during
    `dossier run`, the command R10.4 promises tracking cannot change. So what
    comes back may reach an MLflow tag, the link `Tracker` records and a line in
    the terminal, and nothing else: no cache key, no manifest, no score, no file
    under `runs/` or `.dossier/` (R13.4).
    """

    def register(
        self,
        *,
        record: VersionRecord,
        experiment: str,
    ) -> PublishedVersion:
        """Find the version `record` identifies, or create it ready.

        Found, never assumed. MLflow creates a new logged model every time it is
        asked by name, so a registry that did not look first would leave one per
        run and compare nothing with nothing (R13.1 row 2). The pair that finds
        it is the name and the pipeline hash: neither half identifies alone
        (R13.1 rows 4-5).
        """
        ...


class EmbeddingProvider(Protocol):
    """A model asked for vectors (spec 018). Reached only on a cache miss (R18.3).

    Its implementations live in `dossier.infrastructure.models`, left of the
    hash boundary with every other model client (R0.19): a vector is a model's
    answer, cached as a stage's answer is.
    """

    # The prompt tokens the model counted for the last request, or `None` when
    # it does not say. Read for that request's trace (R11.33).
    last_tokens: int | None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the order given."""
        ...


class Chunker(Protocol):
    """What cuts a document into the pieces an index searches (R18.1).

    `identity` names the chunker and its version, and `settings` how it was
    told to cut. Both are part of every chunk's id (R18.2), so a change of
    either re-chunks rather than mixing two cuts in one index.
    """

    identity: str
    settings: Mapping[str, object]

    def chunk(self, text: str) -> list[Chunk]: ...


class IndexSink(Protocol):
    """The embedding index, written by `dossier embed` (spec 018).

    The index is derived data. What it answers is the only thing read back:
    the ids and content hashes of the documents it holds, so `embed` writes
    only what changed (R18.4). Nothing it holds enters a key, a manifest or a
    score (R0.19).
    """

    def prepare(self, index: str, column: str) -> None:
        """Create what the index needs, its vectors held as `column` (R18.5)."""
        ...

    def held(self, index: str) -> Mapping[str, str]:
        """Each document the index holds, by id, with the content hash it was written at."""
        ...

    def write(
        self, index: str, document: IndexedDocument, chunks: Sequence[IndexedChunk]
    ) -> None:
        """Replace one document's rows with these, whole or not at all."""
        ...

    def remove(self, index: str, document_ids: Sequence[str]) -> None: ...


class IndexSearch(Protocol):
    """The embedding index, searched by `dossier search` (spec 019).

    Its own port, beside `IndexSink`, because it reads back what the index is
    for -- chunks, their text, their documents' titles and values -- where
    `IndexSink` reads back only ids and content hashes (R18.4). What it reads
    reaches the terminal and MLflow, and nothing else: no key, manifest or
    score (R0.19).
    """

    def models(self, index: str) -> frozenset[str]:
        """The embedding models the index's documents were embedded with (R19.6).

        Empty when the index holds nothing, or does not exist yet.
        """
        ...

    def snapshots(self, index: str) -> Mapping[str, str]:
        """Each document the index holds, by id, with the snapshot it was written at (R19.7)."""
        ...

    def search(
        self,
        index: str,
        *,
        vector: Sequence[float],
        words: str,
        where: Mapping[str, Sequence[str]],
        readers: Sequence[str] | None,
        candidates: int,
    ) -> Lists:
        """The chunks nearest `vector`, and the chunks `words` match, each best first.

        Both lists are filtered alike before they are cut at `candidates`:
        every field of `where` must hold one of its values, a field's value
        being a document's carried value or any of its values when it holds a
        list (R19.4); and with `readers`, a chunk's readers must name one of
        them (R19.10); `None` is every chunk (R19.11). `words` is asked as
        `websearch_to_tsquery('simple', words)`.
        """
        ...
