"""Read the Ollama recorder's log: every text the embedding model was asked about.

    python asked.py embed-calls.jsonl

One block per request: the model, and each text it was asked to embed, on one
line and cut at 200 characters, with how many of the seven canaries the whole
text carried.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canaries import CANARIES, held  # noqa: E402


def main(log: str) -> None:
    lines = Path(log).read_text(encoding="utf-8").splitlines()
    texts = 0
    for line in lines:
        request = json.loads(line)
        print(f"{request['model']} · {len(request['input'])} texts")
        for text in request["input"]:
            texts += 1
            flat = " ".join(text.split())
            shown = flat if len(flat) <= 200 else flat[:199] + "…"
            print(f"  {len(held(text))} of {len(CANARIES)}  {shown}")
    print(f"{len(lines)} requests · {texts} texts")


if __name__ == "__main__":
    main(sys.argv[1])
