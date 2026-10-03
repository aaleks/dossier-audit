#!/usr/bin/env python3
"""The toolkit's stub model, with one more field in its call log: the prompt itself.

`playground/toolkit/stub_model.py` logs a call's length (`prompt_chars`) and
its first line (`prompt_first_line`), which is enough for every other
exercise -- knowing *how many* calls happened and *about which document* is
the claim those exercises check. This exercise's claim is different: that a
value is, or is not, *inside* the text a call carried. For that, the log
needs the text, not its length.

So this launcher is the same server, started the same way, with the same
`--replies` and `--log` -- only `Handler._record` gains one field, `prompt`,
holding the rendered prompt verbatim. Nothing else about the toolkit's stub
is touched, and no other exercise imports this file.

    python stub_model_capturing.py --replies ../resources/replies.json \\
        --port 8099 --log /tmp/dossier25-calls.jsonl
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "toolkit"))

import stub_model  # noqa: E402


class CapturingHandler(stub_model.Handler):
    """`stub_model.Handler`, logging the full prompt beside its length."""

    def _record(
        self, body: dict, prompt: str, reply: str | None, images: Sequence[str]
    ) -> None:
        if self.log_path is None:
            return
        line = {
            "at": datetime.now(UTC).isoformat(),
            "model": body.get("model"),
            "prompt_chars": len(prompt),
            "images": len(images),
            "matched": reply is not None,
            "documents": stub_model.DOCUMENT_KEY.findall(prompt),
            "prompt": prompt,
        }
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(line, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    stub_model.Handler = CapturingHandler
    return stub_model.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
