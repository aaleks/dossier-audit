"""R14.5 — no prompt version is ever read back into a rendered prompt, a key, a score or a file.

The one-way promise spec 013 opens with, and the reason the spec is narrow.
MLflow's prompt registry exists to be loaded from -- `load_prompt` is its
headline -- and dossier takes only the half that writes.

Checked structurally rather than by example, because the failure this guards
against is a future edit, not a current bug: someone reaches for `load_prompt`
because MLflow offers it, and the cost lands three specs away as a cache key
that no checkout can reproduce (R0.4), a prompt reaching a run without review,
and a replay that has to fetch (R0.10).
"""

from __future__ import annotations

import ast
from pathlib import Path

from dossier.domain.ports import PromptRegistry
from dossier.domain.prompts import PublishedPrompt

SOURCE = Path(__file__).resolve().parents[2] / "src" / "dossier"


class TestAPromptVersionIsNeverReadBackIntoARun:
    """R14.5 — a prompt version is read by a person, never by dossier."""

    def test_no_module_loads_a_prompt_from_the_registry(self):
        """Row 1: the one where MLflow is ahead of the disk and the disk wins.

        `load_prompt` is the call that fetches a prompt's text, and it appears
        nowhere under `src/` -- including inside a function, because a lazy
        import is the shape R0.10 names explicitly: it hides from an
        import-level check while reaching the network all the same.

        An `ast` walk rather than a text search, for the reason R0.10's own
        boundary check is one: a comment explaining why dossier does *not*
        call it is not a call, and a test that cannot tell the difference
        punishes the documentation that makes the rule survive.

        The `prompts:/` URI scheme is deliberately **not** banned here. It
        addresses a version, and `link_prompt_version_to_run` takes one to
        record which prompt a run rendered (R14.7) -- a write. Banning the
        scheme would have banned the link this spec exists to make, and would
        have been testing a spelling rather than the promise. The promise is
        carried by the assertion below: no type crossing the port can hold a
        template.
        """
        offenders = []
        for module in SOURCE.rglob("*.py"):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                called = (isinstance(node, ast.Attribute) and node.attr == "load_prompt") or (
                    isinstance(node, ast.Name) and node.id == "load_prompt"
                )
                imported = isinstance(node, ast.ImportFrom) and any(
                    alias.name == "load_prompt" for alias in node.names
                )
                if called or imported:
                    offenders.append(str(module.relative_to(SOURCE)))
        assert not offenders, (
            "a prompt fetched at run time is an input to a key no checkout can "
            "reproduce (R0.4) and a network read on the replay path (R0.10):\n"
            + "\n".join(offenders)
        )

    def test_no_method_and_no_returned_type_can_carry_a_prompt_s_text(self):
        """Row 4 and row 5's boundary: what may cross the port, and what may not.

        Not a count of methods. The port grew a third -- `find`, which R14.7 uses
        to get the version carrying a hash the run already computed -- and
        counting would have called that a violation while a method returning the
        whole template under an innocent name would have passed.

        What is actually forbidden is a prompt's **text** crossing back.
        `PublishedPrompt` is the only thing any of these methods returns, and it
        has no field to carry one, so a future method cannot smuggle one through
        without changing the type that every caller already reads.
        """
        offered = {name for name in dir(PromptRegistry) if not name.startswith("_")}

        assert offered == {"publish", "latest", "find"}, (
            f"the port offers {sorted(offered)}; a new method is a reviewable act, "
            "and this assertion is where the review happens"
        )
        carried = set(PublishedPrompt.__dataclass_fields__)
        assert carried == {"name", "version", "prompt_hash", "created"}, (
            f"PublishedPrompt carries {sorted(carried)}; a field holding a template "
            "would make the registry an input to a run (R14.5)"
        )
