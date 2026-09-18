"""R0.12 — `--replay` writes the reproduced artifacts to a new directory under the
run, and writes nothing if any one of them cannot be reproduced.

The naming half, as a pure decision: where a replay's directory sits, given the
run it reproduces and its own id. The write and the all-or-nothing are proved
through the CLI by the acceptance test.
"""

from __future__ import annotations


class TestAReplayDirectorySitsUnderItsRun:
    """R0.12 — `runs/<run_id>/replays/<replay_id>`."""

    def test_a_replay_is_filed_under_the_run_it_reproduces(self):
        """The one where the replay of `4f1a` at `1e2f` sits under `4f1a`, not beside it."""
        from dossier.domain.store import replay_path

        assert (
            replay_path("20260806T142203Z-4f1a", "20260918T140000Z-1e2f")
            == "runs/20260806T142203Z-4f1a/replays/20260918T140000Z-1e2f"
        )
