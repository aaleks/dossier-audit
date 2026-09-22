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

from pathlib import Path

from dossier.domain.ports import PromptRegistry

SOURCE = Path(__file__).resolve().parents[2] / "src" / "dossier"


class TestAPromptVersionIsNeverReadBackIntoARun:
    """R14.5 — a prompt version is read by a person, never by dossier."""

    def test_no_module_loads_a_prompt_from_the_registry(self):
        """Row 1: the one where MLflow is ahead of the disk and the disk wins.

        `load_prompt` and `prompts:/` are the two spellings of fetching a prompt
        at run time. Neither appears anywhere under `src/`, including inside a
        function -- a lazy import is the shape R0.10 names explicitly, because
        it hides from an import-level check while reaching the network all the
        same.
        """
        offenders = []
        for module in SOURCE.rglob("*.py"):
            text = module.read_text(encoding="utf-8")
            for spelling in ("load_prompt", "prompts:/"):
                if spelling in text:
                    offenders.append(f"{module.relative_to(SOURCE)}: {spelling}")
        assert not offenders, (
            "a prompt fetched at run time is an input to a key no checkout can "
            "reproduce (R0.4) and a network read on the replay path (R0.10):\n"
            + "\n".join(offenders)
        )

    def test_the_port_offers_no_way_to_load_a_prompt(self):
        """Row 4's boundary: what the port does and does not let a caller do.

        `publish` writes and `latest` reads a tag to decide whether to write --
        the one read the promise permits. There is no third method, so a caller
        wanting a prompt's text from the server would have to widen the port,
        which is a reviewable act rather than an import nobody notices.
        """
        offered = {name for name in dir(PromptRegistry) if not name.startswith("_")}

        assert offered == {"publish", "latest"}, (
            f"the port offers {sorted(offered)}; a way to read a prompt's text back "
            "would make the registry an input to a run"
        )
