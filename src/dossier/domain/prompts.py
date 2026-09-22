"""What a prompt declares it needs, what it is given, and what it is called.

Spec 003 for the first two, spec 013 for the third: a prompt's name in MLflow's
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
from collections.abc import Sequence

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


def prompt_name(pipeline: str, step: str) -> str:
    """R13.1 — what a step's prompt is called in MLflow's prompt registry.

    The separator is a dot because MLflow rejects `/` and `:` outright:
    `_validate_model_name` refuses both, so `incident-audit/verify` -- the
    obvious spelling, and the one the rest of these specs would suggest -- was
    never available to choose.

    The pipeline is in the name because a prompt name is global in MLflow while a
    prompt file is resolved against the pipeline's own directory (spec 005). Two
    pipelines each holding a `verify` step would otherwise interleave unrelated
    edits into one version history, and a person diffing v2 against v1 would be
    reading two different pipelines.
    """
    return f"{pipeline}.{step}"
