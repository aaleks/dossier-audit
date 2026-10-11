"""Read the capturing stub's call log: one line per call, and the canaries it carried.

    python calls.py calls.jsonl

A step's call is shown by the document it was about. A judge's call is shown
by its claim, the candidate answer between `<claim>` and `</claim>`, as the
judge was shown it. Each line ends with how many of the seven canaries the
whole prompt carried: the document, the rubric and the claim together.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canaries import CANARIES, held  # noqa: E402

CLAIM = re.compile(r"<claim>(.*?)</claim>", re.DOTALL)


def main(log: str) -> None:
    lines = Path(log).read_text(encoding="utf-8").splitlines()
    for line in lines:
        call = json.loads(line)
        prompt = call["prompt"]
        documents = (
            ", ".join(call["documents"]) or re.search(r"Document (\S+), in full", prompt)[1]
        )
        claim = CLAIM.search(prompt)
        what = f"judge  {documents}  {claim[1]}" if claim else f"step   {documents}"
        print(f"{what}  ·  {len(held(prompt))} of {len(CANARIES)}")
    print(f"{len(lines)} calls")


if __name__ == "__main__":
    main(sys.argv[1])
