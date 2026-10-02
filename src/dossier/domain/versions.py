"""A pipeline version projected onto an MLflow logged model (spec 013).

Pure, as the dataset projection is (spec 012): what a version holds is a
decision, and the call that registers it is wiring. `infrastructure/tracking/`
does the registering.

A note on the word. In `dossier` a **model** is the LLM, pinned in
`pipeline.yaml` and hashed into every key (spec 009). MLflow's *logged model* is
the thing being evaluated, and what fills that slot here is the **pipeline
version** -- the prompts, schemas, converters and model pin a run used,
identified by its `pipeline_hash`. The LLM appears as a param of the version.
Blurring the two would read as though `dossier` published the LLM.

The projection is one way only. Nothing here reads a version back; what comes
off a server is a `PublishedVersion`, and R13.4 says where it may go.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from dossier.domain.hashing import content_hash
from dossier.domain.resolution import ResolvedPlan
from dossier.domain.tracking import version_params

# The pair that identifies a version, and the reason there are two of them. A
# live spike against MLflow found that filtering logged models on the name alone
# returned every version of the pipeline, and on the hash alone returned every
# pipeline that resolved to it. Only the conjunction returned one (R13.1 rows
# 4-5).
PIPELINE_TAG = "dossier.pipeline"
HASH_TAG = "dossier.version_hash"

# What a version is NOT. The corpus is not part of the pipeline: a run over
# five documents instead of four is the same version measured more widely,
# and folding the count in would make every sync a new row in the Models
# tab with nothing to compare it against.
_NOT_IDENTITY = ("documents",)

# What MLflow calls a logged model that is not a serialised artifact. `dossier`
# registers no files with a version: it is a pointer to a pipeline at a hash,
# and every byte behind it is in git and in the manifest.
MODEL_TYPE = "agent"


@dataclass(frozen=True)
class VersionRecord:
    """What one pipeline version is called, is described by, and is found by.

    Frozen and compared by value, which R13.1 leans on: a version projected
    twice from one plan must be the same version, or a second run would register
    a second row and the comparison this spec exists for would compare a
    pipeline with itself (R0.4).
    """

    name: str
    params: Mapping[str, str]
    tags: Mapping[str, str]

    # No `__hash__`. The dataclass would build one out of the built-in `hash()`,
    # which is salted per process and is the one digest this repository forbids
    # (R0.7, R0.4). Nothing needs a `VersionRecord` in a set: what R13.1 leans on
    # is equality, and the generated `__eq__` compares the dicts by value.
    __hash__ = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PublishedVersion:
    """What a registry says about a version it registered or found (R13.1).

    The second thing in `dossier` that came *back* from a tracking server, and
    the reason `VersionRegistry` is a port of its own rather than a method on
    `Tracker`, which returns nothing (R15.5 row 2): R0.17 lets tracking read
    back only what a spec fences, and spec 013 fences this. Every field here may
    reach an MLflow tag, the link `Tracker` records and a line in the terminal,
    and none of it may reach a cache key, a manifest, a score or any file on disk
    (R13.4).
    """

    version_id: str
    name: str
    pipeline_hash: str
    # Whether this call made it. R13.1 row 2 is a claim about this: the second
    # run of an unchanged pipeline finds what the first registered.
    created: bool
    params: Mapping[str, str] = field(default_factory=dict)


def version_hash(params: Mapping[str, str]) -> str:
    """One digest over everything that produced a run's answers (R13.1).

    `pipeline_hash` is the hash of `pipeline.yaml` and nothing else, so two runs
    whose prompts differ share it. A version keyed on it would put an edited
    prompt in the same row as the prompt it replaced, and "did the edit help"
    -- the question the Models tab is opened with -- would have no two rows to
    compare.

    So the identity is every param that describes what ran: the pipeline hash,
    each step`s prompt, schema and generated-schema hashes, the converters and
    the model pin. Everything a stage key is made of (spec 005) is in there,
    which is the same claim from the other side: two versions that would produce
    identical artifacts are one version.

    Sorted before hashing, and rendered as `key=value` lines, so the digest is
    byte-identical across runs and machines (R0.4, R5.6, R0.7).
    """
    identity = sorted((key, value) for key, value in params.items() if key not in _NOT_IDENTITY)
    joined = "\n".join(f"{key}={value}" for key, value in identity)
    return content_hash(joined.encode("utf-8"))


def version_record(plan: ResolvedPlan) -> VersionRecord:
    """The one logged model a resolved plan projects onto (R13.1).

    Named after the pipeline, because that is what a person compares versions
    *of*; the hash tells two of them apart and is a param, not part of the name.
    A name carrying the hash would make every version its own object in MLflow's
    Models list, which is the flat list this spec exists to replace.

    The params are `version_params` (R11.18) plus the model pin, so the run's
    record and the version's say the same thing about one plan -- one function
    over one set of data, rather than two computations that happen to agree.
    """
    params = dict(version_params(plan))
    # Beside the prompt and schema hashes rather than in place of them: a version
    # whose only change is the LLM is still a different version, and the pin is
    # already in `pipeline_hash` (spec 005). Recorded plainly so the Models tab
    # can be read without resolving a hash.
    params["model"] = plan.model
    # NOT `pipeline_hash`. That is `text_hash(pipeline.yaml)` and covers
    # neither the prompts nor the schemas, so under it an edited prompt was
    # the same version -- which is the one comparison this spec exists for.
    # The identity is a hash over everything that produced the answers.
    params["version_hash"] = version_hash(params)
    # Both halves off the one plan. A caller passing the pipeline name
    # separately could hand a version of `incident-audit` the name of another
    # pipeline, which is exactly the mix-up row 4 is a counter-example about.
    return VersionRecord(
        name=plan.pipeline,
        params=params,
        tags={PIPELINE_TAG: plan.pipeline, HASH_TAG: params["version_hash"]},
    )
