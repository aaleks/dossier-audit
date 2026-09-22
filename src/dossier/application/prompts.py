"""Publishing a pipeline's prompts as MLflow prompt versions (spec 013).

The use case `dossier prompts publish` runs. It reads each prompt and rubric out
of the pipeline's own directory, projects them onto the set `publish_set`
decides (R14.1, R14.2), and hands each to a `PromptRegistry` it is given rather
than one it builds -- the registry is infrastructure, and which one this is
belongs to the composition root.

Nothing here reads a prompt back. A version is written from the pipeline
directory and read by a person; the files on disk stay the only source a run
renders from (R14.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from dossier.domain.hashing import short
from dossier.domain.pipeline import PipelineConfig
from dossier.domain.ports import PromptRegistry
from dossier.domain.prompts import PROMPT_HASH_TAG, PublishedPrompt, publish_set


def publish_prompts(
    registry: PromptRegistry,
    *,
    config: PipelineConfig,
    directory: Path,
    rubrics: Mapping[str, Mapping[str, str]] | None = None,
) -> list[PublishedPrompt]:
    """Every prompt `config` names, published under its own name (R14.1, R14.2).

    `directory` is the pipeline's own -- `prompts/` and `rubrics/` are resolved
    against it, as spec 005 resolves every path a step writes, because a pipeline
    is self-contained and can be moved.

    `rubrics` maps a step id to the rubric each of its judged fields names, and
    arrives already loaded: reading a field declaration is `config/`'s job, and a
    use case is handed what it needs rather than going to find it.
    """
    texts = {
        path: (directory / path).read_text(encoding="utf-8") for path in _paths(config, rubrics)
    }
    published: list[PublishedPrompt] = []
    for prompt in publish_set(config, texts, rubrics=rubrics):
        # Asked before written, because `register_prompt` versions
        # unconditionally: called again with the text already at the top of the
        # history it creates a second, identical version, and a person opening
        # the registry finds two entries to compare that differ in nothing
        # (R14.4). This read is the one the one-way promise permits -- it
        # decides a write and reaches no key, score or file (R14.5 row 4).
        held = registry.latest(prompt.name)
        if held is not None and held.prompt_hash == prompt.tags[PROMPT_HASH_TAG]:
            published.append(held)
            continue
        published.append(
            registry.publish(
                name=prompt.name,
                template=prompt.template,
                tags=prompt.tags,
                commit_message=_commit_message(prompt.tags),
            )
        )
    return published


def _paths(
    config: PipelineConfig, rubrics: Mapping[str, Mapping[str, str]] | None
) -> list[str]:
    """Every file to read, each once.

    A dict rather than a set: two steps naming one prompt file read it once and
    the order stays the pipeline's, which is what `publish_set` then publishes in
    (R14.1 row 3).
    """
    paths = {step.prompt: None for step in config.steps}
    for declared in (rubrics or {}).values():
        paths.update(dict.fromkeys(declared.values()))
    return list(paths)


def _commit_message(tags: Mapping[str, str]) -> str:
    """What MLflow's version list shows beside each entry (R14.3).

    A column of blank messages is a version history nobody reads without opening
    every row, and the path plus eight characters of the hash is what tells two
    entries apart at a glance.
    """
    return f"dossier: {tags['dossier.path']} {short(tags[PROMPT_HASH_TAG])}"
