"""What a prompt declares it needs, what it is given, and what it is called.

Spec 003 for the first two, spec 014 for the third: a prompt's name in MLflow's
registry is a pure decision about a pipeline name and a step id, so it lives
here beside the other decisions a prompt is subject to rather than next to the
call that sends it.

Two failures this closes, and both are quiet. A declared input that no
placeholder injects is a silent no-op: it sits in the stage's key, so changing it
re-runs the stage for a reason nothing can see (R5.2). An undeclared placeholder
is worse -- nothing fills it, so `{{reference}}` reaches the model as six literal
characters and the answer that comes back looks entirely plausible.

Placeholders are matched against inputs **as declared**, sugar included: a step
writing `input: previous` writes `{{previous}}`. R3.6 says load-time, and at load
time `previous` has not been expanded -- spec 004 does that later, against a
pipeline this module has already checked.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from dossier.domain.hashing import content_hash, normalised_text
from dossier.domain.pipeline import PipelineConfig
from dossier.domain.tracking import check_namespace, namespaced

# `{{ name }}` with optional inner whitespace. Rejecting the spaced form would be
# defensible and would waste an afternoon; it is unambiguously the same thing.
#
# The `@kind` suffix is part of the name, not a separate thing to strip (R3.11).
# A step may read two kinds of the same source -- `[documents, documents@page_images]`
# -- and those are two inputs that must reach two different placeholders.
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_()]*(?:@[a-z][a-z0-9_]*)?)\s*\}\}")

# Fenced blocks, both markdown fences. A prompt that teaches the model an output
# format contains braces, and treating those as inputs would make the most useful
# prompts unwritable (R3.6 example 4).
_FENCED = re.compile(r"^(?P<fence>```|~~~).*?^(?P=fence)", re.MULTILINE | re.DOTALL)


# `_validate_model_name` in mlflow.utils.validation refuses both outright, and a
# prompt is a registered model underneath. Checked here rather than at the call
# that sends, so the refusal is dossier's sentence and arrives before the first
# request rather than partway through a publish (R14.1 row 5).
_REJECTED_BY_MLFLOW = ("/", ":")


# The tag that ties a version to the provenance record of the run that rendered
# it. Named once, because the publish that writes it and the compare that reads
# it back must agree (R14.3, R14.4).
PROMPT_HASH_TAG = "dossier.prompt_hash"


def placeholders_in(prompt: str) -> set[str]:
    """Every input name the prompt injects, ignoring fenced code."""
    return set(_PLACEHOLDER.findall(_FENCED.sub("", prompt)))


def check_placeholders(*, step: str, declared: Sequence[str], prompt: str) -> None:
    """R3.6 — the two sides name exactly the same inputs.

    The two mismatches are reported separately because they have different
    fixes: one is a prompt that forgot an input, the other is a prompt asking for
    something the step never reads.
    """
    injected = placeholders_in(prompt)
    wanted = set(declared)

    missing = sorted(wanted - injected)
    if missing:
        raise ValueError(
            f"step {step!r} declares {missing} but its prompt never injects "
            f"{'them' if len(missing) > 1 else 'it'}. A declared input that no "
            "placeholder uses is part of the stage's cache key and reaches the "
            "model not at all."
        )

    undeclared = sorted(injected - wanted)
    if undeclared:
        raise ValueError(
            f"step {step!r} injects {undeclared}, which "
            f"{'are' if len(undeclared) > 1 else 'is'} "
            f"not among its declared inputs {sorted(wanted)}. Nothing fills an undeclared "
            "placeholder, so it would reach the model as literal braces."
        )


def empty_inputs(contents: Mapping[str, Sequence[str]], *, parts: int = 0) -> tuple[str, ...]:
    """The inputs a call is about, when every one is empty; `()` when any holds something.

    `contents` is what each input holds, unwrapped: a document's text, or each
    member's in a set. Empty is the empty string, so a scan whose markdown is
    only its page anchors is not empty, and asking about it is how its emptiness
    becomes a finding (spec 008). A part is content: a `per_part` call carries
    its picture, whatever its placeholder holds (R8.11).

    Four rules closed one shape each of a model asked about an input that came
    out empty (R6.13, R6.21, R3.16, R3.19), each found after answers about
    nothing had been cached. This is asked of every call, so the next shape is
    stopped where it arrives (R6.29).
    """
    if parts or any(text for texts in contents.values() for text in texts):
        return ()
    return tuple(contents)


def render(prompt: str, values: dict[str, str]) -> str:
    """Fill every placeholder with the text of the input it names.

    Multiple inputs go under distinct labelled tags rather than concatenated
    (spec 003, "Prompt files"), and the tags are the prompt author's -- this only
    replaces what is inside the braces.

    Fenced blocks are left exactly as written. They are the same blocks
    `placeholders_in` refuses to read inputs out of, and for the same reason:
    substituting there would corrupt the example code a prompt is using to teach
    the model a format.

    Only ever called after `check_placeholders` has passed, so a missing key here
    is a defect rather than a user error, and `KeyError` is the right noise.
    """

    def fill(text: str) -> str:
        return _PLACEHOLDER.sub(lambda found: values[found.group(1)], text)

    rendered: list[str] = []
    end_of_last_fence = 0
    for fence in _FENCED.finditer(prompt):
        rendered.append(fill(prompt[end_of_last_fence : fence.start()]))
        rendered.append(fence.group(0))
        end_of_last_fence = fence.end()
    rendered.append(fill(prompt[end_of_last_fence:]))

    return "".join(rendered)


def prompt_name(pipeline: str, step: str, *, prefix: str = "") -> str:
    """R14.1 — what a step's prompt is called in MLflow's prompt registry.

    The separator is a dot because MLflow rejects `/` and `:` outright:
    `_validate_model_name` refuses both, so `incident-audit/verify` -- the
    obvious spelling, and the one the rest of these specs would suggest -- was
    never available to choose.

    The pipeline is in the name because a prompt name is global in MLflow while a
    prompt file is resolved against the pipeline's own directory (spec 005). Two
    pipelines each holding a `verify` step would otherwise interleave unrelated
    edits into one version history, and a person diffing v2 against v1 would be
    reading two different pipelines.

    Only the pipeline is checked. R3.2 already holds a step id to
    `[a-z][a-z0-9_]*`, so no step can carry either character and a guard there
    would be unreachable; a pipeline's name is its directory under `pipelines/`
    and nothing constrains it at all (R14.1 row 5).

    `prefix` is the namespace the name was missing (R10.13, which replaced
    R14.8's prefix for prompts alone). A name that carries its pipeline is
    unique within one workspace and no further, so two checkouts holding
    `incident-audit` would publish into one history. Empty, it is nothing, and
    the name is exactly what it was before the prefix existed -- which is what
    lets a person who never sets it see no change at all.
    """
    for character in _REJECTED_BY_MLFLOW:
        if character in pipeline:
            raise ValueError(
                f"pipeline {pipeline!r} cannot be published: MLflow rejects {character!r} "
                "in a prompt name, and the name is composed from the pipeline and the "
                "step. Rename the pipeline directory, or publish a pipeline whose name "
                "holds neither '/' nor ':'."
            )
    check_namespace(prefix)
    return namespaced(f"{pipeline}.{step}", prefix)


@dataclass(frozen=True)
class PromptToPublish:
    """One prompt a publish would send: what it is called, what it says, and its tags."""

    name: str
    template: str
    tags: dict[str, str]


def judge_prompt_name(pipeline: str, field: str, *, prefix: str = "") -> str:
    """R14.2 — what a judged field's rubric is called.

    The field rather than the step, because no step owns a rubric: two steps
    declaring one field declaration both see it, and naming it after either
    would be a coin toss a reader could not reconstruct. `judge.` sits in the
    middle so a registry listing groups a pipeline's rubrics together and so the
    name cannot collide with a step id, which R3.2 holds to `[a-z][a-z0-9_]*`
    and therefore cannot contain a dot.
    """
    return f"{prompt_name(pipeline, 'judge', prefix=prefix)}.{field}"


def rubric_links(
    pipeline: str,
    rubric_hashes: Mapping[str, str],
    *,
    withheld: Collection[str] = (),
    prefix: str = "",
) -> list[tuple[str, str]]:
    """R14.9 — the rubric versions a judge's record looks for: a name and a hash each.

    `rubric_hashes` maps a judged field to the `text_hash` of its rubric, which
    is the value R14.3 tags a published version with, so a version is found by
    the words it holds rather than by being newest.

    A withheld field is left out. Nothing was judged with its rubric, and a
    rubric edited since its calibration -- the commonest reason to withhold
    (R7.15) -- would otherwise link words no reported figure came from.

    In field order, so two evals of one pipeline ask the registry the same
    questions in the same order (R0.4).
    """
    return [
        (judge_prompt_name(pipeline, field, prefix=prefix), rubric_hashes[field])
        for field in sorted(rubric_hashes)
        if field not in withheld
    ]


def publish_set(
    config: PipelineConfig,
    texts: Mapping[str, str],
    rubrics: Mapping[str, Mapping[str, str]] | None = None,
    *,
    prefix: str = "",
) -> list[PromptToPublish]:
    """R14.1 — the prompts a pipeline publishes, one per step.

    Handed the text rather than reading it, so the decision about what is
    published under which name stays in domain/ and stays provable without a
    workspace. `texts` is keyed by the path the step writes, which is also why
    two steps naming one file publish twice: the lookup is shared, the name is
    not.

    Declaration order, not sorted. It is the order a person reads the pipeline
    in and the order the terminal line prints, and nothing here reaches a cache
    key -- the ordering rule that R5.6 imposes on hashed collections does not
    apply to a list nobody hashes.

    `rubrics` arrives per step -- `{step id: {field: rubric path}}` -- rather
    than pre-merged, so the decision that judging one field is one job however
    many steps declare it is made here and not by whoever loaded the
    declarations (R14.2). The rubrics follow the steps for the same reason the
    steps are in declaration order: it is the order the terminal prints.
    """
    published: list[PromptToPublish] = []
    for step in config.steps:
        published.append(
            _to_publish(
                name=prompt_name(config.name, step.id, prefix=prefix),
                pipeline=config.name,
                path=step.prompt,
                text=texts[step.prompt],
                owner=("dossier.step", step.id),
            )
        )
    seen = {prompt.name for prompt in published}
    for step in config.steps:
        for field, path in (rubrics or {}).get(step.id, {}).items():
            name = judge_prompt_name(config.name, field, prefix=prefix)
            # Judging one field is one job however many steps declare it. The
            # name is the field's, so the second sighting is a duplicate by
            # construction rather than something to compare paths over (R14.2).
            if name in seen:
                continue
            seen.add(name)
            published.append(
                _to_publish(
                    name=name,
                    pipeline=config.name,
                    path=path,
                    text=texts[path],
                    # The field, never a step: no step owns a rubric.
                    owner=("dossier.field", field),
                )
            )
    return published


def _to_publish(
    *, name: str, pipeline: str, path: str, text: str, owner: tuple[str, str]
) -> PromptToPublish:
    """One prompt, with the four tags R14.3 puts on every version.

    The template and the hash come from one local, so the words published and
    the digest taken over them cannot drift apart. `owner` is the one tag that
    differs between a step's prompt and a rubric, and it is a parameter rather
    than a branch so that neither kind can quietly lose its other three.
    """
    template = normalised_text(text)
    owner_tag, owner_value = owner
    return PromptToPublish(
        name=name,
        template=template,
        tags={
            # The full 64 characters, never the eight a log line shows (R0.7).
            # This is the one value that ties a version in MLflow back to the
            # provenance record of the run that rendered it, and a prefix would
            # tie it to several.
            PROMPT_HASH_TAG: content_hash(template.encode("utf-8")),
            "dossier.pipeline": pipeline,
            owner_tag: owner_value,
            "dossier.path": path,
        },
    )


@dataclass(frozen=True)
class PublishedPrompt:
    """What a registry says about a prompt version it created or found (R14.3).

    Comes *back* from a tracking server, which is why publishing prompts has a
    port of its own rather than a method on `Tracker`, whose every method sends
    and returns nothing (R15.5 row 2): R0.19 lets tracking read back only what a
    spec fences, and spec 014 fences this. Every field here may reach a tag, a
    link and the terminal line, and nothing else: no key, no manifest, no file
    under `runs/`, `gold/` or the pipeline's own directory (R14.5).
    """

    name: str
    version: int
    prompt_hash: str
    created: bool
