"""Whether a judge may be quoted, and whether its calibration still applies.

Two pure decisions *about* a judge, neither of which calls one. That is what
makes them buildable while the model client does not exist, and it is why the
functions here take a measured agreement figure rather than measuring it --
producing that number is R7.11, and R7.11's threshold is deliberately still
`OPEN`: it needs at least twenty human-scored cases before a figure means
anything, and the figure belongs to the domain expert who signs off the gold set.

So the machinery is here and the number is not, which is the right way round. A
threshold invented to make a module feel finished becomes a test, becomes a gate,
and is discovered to be arbitrary three features later.

What both rules buy is honest silence. A judge that has not been shown to agree
with a human still produces a percentage, and that percentage reads exactly like
evidence. Refusing to print it is the only thing that tells the two apart.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Below this, an agreement figure is not a weak measurement -- it is not a
# measurement. R7.11 row 3 says so: report "not measurable at this N", never a
# percentage. Twenty is the spec's number, not one chosen here.
MINIMUM_SAMPLE = 20


class NotCalibrated(ValueError):
    """There is no usable agreement figure for this judge.

    Distinct from *below the threshold*, which is a judge that was measured and
    did not do well enough. This is a judge that was not measured at all, or was
    measured on too small a sample to mean anything -- and the two need different
    work, so a report that called both "not eligible" would send someone to
    tune a prompt when what is missing is gold data.
    """


class Calibration(BaseModel):
    """What a judge was measured at, and what it was measured against.

    The model identifier and the rubric hash are part of the measurement rather
    than metadata about it: an agreement figure without them says a judge agreed
    with a human, without saying which judge or on what question (R7.6, R7.11
    row 2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    judge_model: str
    rubric_hash: str
    # The wrapper dossier puts the rubric in, hashed. Optional only so a file
    # from before R7.19 still loads: it then reads as stale, never as fresh.
    prompt_hash: str | None = None
    agreement: float
    sample_size: int


def is_eligible(calibration: Calibration | None, *, threshold: float) -> bool:
    """Whether this judge's verdicts may be reported as a metric (R7.5).

    The bound is inclusive: a judge measured at precisely the agreed figure has
    met the agreed figure. Stated in the spec, and the kind of thing implemented
    as `>` by accident.

    Raises rather than returning `False` where there is nothing to compare. A
    field with no judge, or a calibration from too small a sample, is not a judge
    that scored badly -- and collapsing the two would report missing gold data as
    a quality problem.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            f"an agreement threshold is a proportion between 0 and 1; got {threshold!r}. "
            "A threshold of 85 rather than 0.85 makes every judge ineligible forever, "
            "and reads like strict configuration rather than a typo."
        )

    if calibration is None:
        raise NotCalibrated(
            "this field has no judge calibration. A field scored by exact match has "
            "no judge and no threshold, and one scored by a judge must be measured "
            "before it can be reported (R7.5, R7.11)."
        )

    if calibration.sample_size < MINIMUM_SAMPLE:
        raise NotCalibrated(
            f"agreement was measured on {calibration.sample_size} case(s), and "
            f"{MINIMUM_SAMPLE} is the minimum at which the figure means anything. "
            "Report this as not measurable at this N, never as a percentage "
            "(R7.11 example 3)."
        )

    return calibration.agreement >= threshold


def is_stale(
    calibration: Calibration, *, judge_model: str, rubric_hash: str, prompt_hash: str
) -> bool:
    """Whether a calibration was measured against something else (R7.6, R7.19).

    Any change alone is enough. The rule says "the judge model *or* its
    rubric", and joining them with `and` would go stale only when both moved --
    the case that almost never happens. The judge prompt -- the wrapper dossier
    puts the rubric in -- is the third input (R7.19): an edit to it changes what
    every judge is asked with no byte of the author's rubric moving. A
    calibration that recorded no prompt hash was measured under a prompt nobody
    recorded, which is not the same as measured under this one.

    The model identifier is compared exactly. R0.6 forbids an unpinned
    identifier, so two pins differing by their date are two different models, and
    comparing by family or prefix would let a calibration survive the version
    change it exists to catch.

    A grown sample is deliberately not stale. More gold data does not invalidate
    a measurement made on less; it invites a re-measure, and treating growth as
    staleness would punish the one behaviour the gold set wants to encourage.
    """
    return (
        calibration.judge_model != judge_model
        or calibration.rubric_hash != rubric_hash
        or calibration.prompt_hash != prompt_hash
    )
