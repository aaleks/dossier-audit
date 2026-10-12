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

from collections.abc import Collection, Mapping, Sequence
from math import sqrt
from statistics import NormalDist

from pydantic import BaseModel, ConfigDict

# Below this, an agreement figure is not a weak measurement -- it is not a
# measurement. R7.11 row 3 says so: report "not measurable at this N", never a
# percentage. Twenty is the spec's number, not one chosen here.
MINIMUM_SAMPLE = 20

# Below this many unsupported cases, the share a judge caught is not a
# measurement (R7.31): 1 of 1 is 100% and shows nothing. Eight is the count in
# R7.11's sample, agreed by a.aleks on 2026-09-26, not a number chosen here.
MINIMUM_UNSUPPORTED = 8

# The two-sided 95% z, taken rather than typed as 1.96 (R7.26): the bound is
# then a function of its two counts alone, and the same on every machine.
_Z = NormalDist().inv_cdf(0.975)


class NotCalibrated(ValueError):
    """There is no usable agreement figure for this judge.

    Distinct from *below the threshold*, which is a judge that was measured and
    did not do well enough. This is a judge that was not measured at all, or was
    measured on too small a sample to mean anything -- and the two need different
    work, so a report that called both "not eligible" would send someone to
    tune a prompt when what is missing is gold data.
    """


class Tally(BaseModel):
    """How many of one half of a sample the judge agreed on, out of how many (R7.28).

    Counts rather than a rate, because 8 of 8 and 80 of 80 are both 100% and
    only the count says how far to trust it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agreed: int
    cases: int

    @property
    def rate(self) -> float | None:
        """The share agreed, or `None` for a half with no cases in it.

        None rather than 0 or 1: no unsupported case in a sample is not every
        unsupported case caught, and 0 of 0 read as 100% would credit the judge
        for a test it never sat.
        """
        return self.agreed / self.cases if self.cases else None


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
    # What the agreement does not say (R7.26 - R7.29). Optional so a file
    # written before them still loads, and gates as it did: the gate reads the
    # agreement (R7.5). `kappa` is also None for a sample it cannot measure.
    lower_bound: float | None = None
    kappa: float | None = None
    supported: Tally | None = None
    unsupported: Tally | None = None


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


def withholding(
    calibration: Calibration | None,
    *,
    judge_model: str,
    rubric_hash: str,
    prompt_hash: str,
    threshold: float | None,
    threshold_file: str = "judge.yaml",
    unsupported: float | None = None,
) -> str | None:
    """Why a judged field may not be reported, or `None` when it may (R7.15).

    R7.5 and R7.6 are the decisions; this asks them in order and words the
    answer. Four states withhold a field, and each says which it is rather
    than all four reading as "no score", because they want four different
    fixes: never measured wants a `dossier calibrate`; a stale calibration
    wants a re-measure, and says which of the judge, the rubric or the prompt
    moved; no bar wants a line in the gold set's threshold file (R7.20); and
    one below the bar wants a better judge or a figure somebody agrees to
    lower. Stale is checked before the bar, because a figure measured against
    something else is not a figure to compare with anything.

    `unsupported` is the share of unsupported cases the judge must catch, where
    the gold set declares one (R7.30), checked after the agreement (R7.31).
    """
    if calibration is None:
        return "never measured -- run `dossier calibrate`"
    if is_stale(
        calibration, judge_model=judge_model, rubric_hash=rubric_hash, prompt_hash=prompt_hash
    ):
        if calibration.judge_model != judge_model:
            moved = f"measured against {calibration.judge_model}"
        elif calibration.rubric_hash != rubric_hash:
            moved = "the rubric has changed since"
        elif calibration.prompt_hash is None:
            moved = "measured under a judge prompt nobody recorded (R7.19)"
        else:
            moved = "the judge prompt has changed since (R7.19)"
        return f"calibration is stale: {moved}"
    if threshold is None:
        return f"no agreement threshold declared in {threshold_file}"
    try:
        if not is_eligible(calibration, threshold=threshold):
            return f"agreement {calibration.agreement} is below the agreed {threshold}"
    except NotCalibrated as error:
        return str(error)
    if unsupported is None:
        return None
    return _unsupported_withheld(calibration.unsupported, bar=unsupported)


def _unsupported_withheld(half: Tally | None, *, bar: float) -> str | None:
    """Why the unsupported half keeps a field out of the report, or `None` (R7.31).

    Three different fixes, so three different messages: a calibration from
    before the halves were counted wants measuring again; a half too small to
    mean anything wants more unsupported cases in the sample; and a judge below
    the bar wants a better judge. The bound is inclusive, as R7.5's is.
    """
    if half is None:
        return (
            "measured before its unsupported cases were counted -- run `dossier calibrate` "
            "(R7.26)"
        )
    if half.cases < MINIMUM_UNSUPPORTED:
        return (
            f"the sample holds {half.cases} unsupported case(s), and {MINIMUM_UNSUPPORTED} "
            "is the minimum at which the unsupported bar means anything (R7.31)"
        )
    caught = half.agreed / half.cases
    if caught < bar:
        return (
            f"unsupported {half.agreed} of {half.cases} ({caught:.1%}) is below the "
            f"agreed {bar:.1%}"
        )
    return None


def require_measurable(field: str, count: int) -> None:
    """Refuse a sample too small to produce a figure that means anything (R7.11 row 3).

    Before a single judge call is made: judging it anyway would spend twenty
    calls to arrive at a number nobody may quote, then leave a file behind that
    reads exactly like a calibration (R7.14 row 3).
    """
    if count < MINIMUM_SAMPLE:
        raise NotCalibrated(
            f"{field}: the sample holds {count} case(s), and {MINIMUM_SAMPLE} is the "
            "minimum at which agreement means anything. Report this as not measurable at "
            "this N, never as a percentage (R7.11 example 3)."
        )


def require_held(field: str, documents: Sequence[str], *, held: Collection[str]) -> None:
    """Refuse a sample whose cases name a document the judge would be shown nothing of (R7.14).

    Before a single judge call is made, as a short sample is refused: a case
    about a document this workspace does not hold -- not synced yet, or a key
    mistyped -- cannot be judged, and measuring the rest would be another
    sample's figure.
    """
    missing = sorted({document for document in documents if document not in held})
    if missing:
        raise NotCalibrated(
            f"{field}: the sample's cases name {', '.join(missing)}, which this workspace "
            "does not hold. Sync and convert it, or correct the sample; a judge shown "
            "nothing of a document is not measured on it (R7.14 row 7)."
        )


def agreement(
    *, verdicts: Mapping[str, bool], human: Mapping[str, bool]
) -> tuple[float, tuple[str, ...]]:
    """What proportion of the sample the judge and the reviewer agreed on, and where not.

    Over the cases the reviewer scored, which is the sample R7.11 measures. A
    case the judge could not be asked about is absent from `verdicts` and counts
    as a disagreement rather than being dropped: a judge that fails on the hard
    half of a corpus and is scored on the rest would report a figure the corpus
    does not support.
    """
    if not human:
        raise ValueError("no human-scored cases: there is nothing to agree with")

    disagreed = tuple(case for case in sorted(human) if verdicts.get(case) is not human[case])
    agreed = len(human) - len(disagreed)
    return agreed / len(human), disagreed


def lower_bound(*, agreed: int, cases: int) -> float:
    """The 95% Wilson lower bound on an agreement of `agreed` in `cases` (R7.26).

    How low the judge's true rate of agreement could be and still produce this
    sample. Wilson's rather than the textbook interval's, because a calibration
    is often at 100% or near it, where the textbook interval collapses to a
    width of zero and claims a certainty twenty cases cannot give.

    The counts are the agreement's, a case the judge could not be asked
    included as a disagreement (R7.11), so the bound and the figure it bounds
    are over the same cases.
    """
    if not 0 <= agreed <= cases or cases == 0:
        raise ValueError(
            f"{agreed} agreed of {cases} case(s) is not a sample: a bound needs at "
            "least one case, and no more agreed than there were"
        )
    rate = agreed / cases
    spread = _Z * _Z / cases
    centre = rate + spread / 2
    margin = _Z * sqrt(rate * (1 - rate) / cases + spread / (4 * cases))
    # 0 of n is exactly 0, and floating point lands a hair either side of it:
    # below for 19 sample sizes up to 500, clamped, since no rate is below 0;
    # above for 65, 0 of 20 among them, which prints as 0.0% all the same (R7.26).
    return max(0.0, (centre - margin) / (1 + spread))


def kappa(*, verdicts: Mapping[str, bool], human: Mapping[str, bool]) -> float | None:
    """Cohen's kappa between the judge and the reviewer, or `None` (R7.27).

    Agreement beyond what the two would reach by chance, chance being set by
    how often each said supported. A case the judge could not be asked is
    counted as the opposite of the reviewer's verdict, so kappa counts the same
    disagreements the agreement does (R7.11).

    `None` when the reviewer marked every case the same way. Chance agreement
    then depends on the judge alone, and kappa is 0 or undefined whatever the
    judge did: a figure that says nothing, which would read as one that does.

    Worked in counts, with one division at the end, so a perfect judge is
    exactly 1 and a judge that never says no is exactly 0.
    """
    if not human:
        raise ValueError("no human-scored cases: there is nothing to agree with")
    cases = len(human)
    said = {case: verdicts.get(case, not verdict) for case, verdict in human.items()}
    human_yes = sum(human.values())
    if human_yes in (0, cases):
        return None
    judge_yes = sum(said.values())
    agreed = sum(said[case] is verdict for case, verdict in human.items())
    by_chance = judge_yes * human_yes + (cases - judge_yes) * (cases - human_yes)
    return (agreed * cases - by_chance) / (cases * cases - by_chance)


def by_verdict(
    *, verdicts: Mapping[str, bool], human: Mapping[str, bool]
) -> tuple[Tally, Tally]:
    """The supported cases and the unsupported ones, each as agreed of cases (R7.28).

    Apart, because catching an unsupported claim is the judge's whole job
    (R7.12), and a judge strong on the supported half can hide a weak other
    half inside one agreement figure. A case the judge could not be asked
    counts against its own half, as it counts against the agreement (R7.11).
    """

    def half(supported: bool) -> Tally:
        cases = [case for case, verdict in human.items() if verdict is supported]
        return Tally(
            agreed=sum(verdicts.get(case) is supported for case in cases), cases=len(cases)
        )

    return half(True), half(False)


def calibration(
    *,
    verdicts: Mapping[str, bool],
    human: Mapping[str, bool],
    judge_model: str,
    rubric_hash: str,
    prompt_hash: str,
) -> Calibration:
    """The measurement, recorded with what it was made against (R7.11 row 2).

    The model identifier, the rubric hash and the prompt hash travel with the
    figure because an agreement number on its own says a judge agreed with a
    human without saying which judge, or on what question -- and `is_stale`
    needs all three to notice when any has moved since (R7.6, R7.19).

    With it, what the agreement hides: how sure it is, how much of it chance
    would give, and which half of the sample the judge gets wrong -- each over
    the same cases (R7.26 - R7.29).
    """
    measured, disagreed = agreement(verdicts=verdicts, human=human)
    supported, unsupported = by_verdict(verdicts=verdicts, human=human)
    return Calibration(
        judge_model=judge_model,
        rubric_hash=rubric_hash,
        prompt_hash=prompt_hash,
        agreement=measured,
        sample_size=len(human),
        lower_bound=lower_bound(agreed=len(human) - len(disagreed), cases=len(human)),
        kappa=kappa(verdicts=verdicts, human=human),
        supported=supported,
        unsupported=unsupported,
    )
