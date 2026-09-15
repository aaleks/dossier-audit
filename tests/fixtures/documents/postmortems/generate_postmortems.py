"""Regenerate the synthetic postmortem PDFs in ./pdf.

These are fixtures, not project code. Sixteen fabricated IT incident
postmortems: five complete, five each carrying one known defect, and six more
complete ones written so a root-cause judge has plausible wrong answers to be
calibrated against (R7.11). Layouts differ on purpose so that a converter is
exercised against more than one document shape. Which document is defective and
how is recorded in specs/_fixtures.md.

    python -m venv .venv && .venv/bin/pip install reportlab
    .venv/bin/python generate_postmortems.py

reportlab is deliberately not a dossier dependency - the PDFs are committed, and
this script only exists so they can be reproduced or amended.

Output is byte-stable: reportlab's `invariant` mode fixes document IDs and
timestamps, so regenerating without editing produces identical files.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import OUT  # noqa: E402  (must follow the sys.path edit)
import _docs_calibration  # noqa: E402
import _docs_complete  # noqa: E402
import _docs_defective  # noqa: E402


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in _docs_complete.ALL + _docs_defective.ALL + _docs_calibration.ALL:
        path = fn()
        print(f"{path.name:52s} {path.stat().st_size / 1024:6.1f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
