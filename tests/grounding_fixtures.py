"""Shared values for the spec 006 field-record tests.

Two converted documents: the incident under audit and the procedure `verify`
reads alongside it. Both appear as inputs to the same stage, which is what makes
R6.3's "reference documents are inputs too" row checkable.
"""

from __future__ import annotations

INC_4821 = (
    "Finance confirmed a total exposure CHF 48'200 in late-settlement interest.\n"
    "Severity was assessed as major.\n"
)

OPS_114 = "Procedure OPS-114: incidents above CHF 10'000 require a written review.\n"

STAGE_INPUTS = {"INC-4821": INC_4821, "OPS-114": OPS_114}

LOSS_SPAN = "total exposure CHF 48'200"
SEVERITY_SPAN = "Severity was assessed as major"
PROCEDURE_SPAN = "incidents above CHF 10'000 require a written review"
