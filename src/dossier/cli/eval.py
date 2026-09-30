"""`dossier eval`: a run scored against its gold set, and two runs compared (spec 007)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer

from dossier.application.eval import (
    Judging,
    deltas_artifact,
    finish_eval,
    gold_refusals,
    judge_prompt_hash,
    judge_scores,
    load_calibration,
    load_gold,
    record_comparison,
    score_run,
    scores_artifact,
    start_eval,
)
from dossier.application.manifest import MANIFEST_NAME, Manifest
from dossier.application.plan import latest_manifest
from dossier.application.recording import failed_if_stopped
from dossier.application.run import (
    MissingFromReplay,
    judge_evidence,
    recorded_failures,
    reference_context,
    replay,
    replayed_inputs,
    replayed_parts,
)
from dossier.cli import bootstrap
from dossier.config.environment import environment
from dossier.config.load import (
    JUDGE_FILE,
    ConfigError,
    load_enum_values,
    load_fields,
    load_judge_rubrics,
    load_judge_thresholds,
    load_pipeline,
    load_unsupported_bars,
)
from dossier.domain.datasets import PublishedDataset
from dossier.domain.gold import gold_set_hash
from dossier.domain.grounding import GROUNDED, judge_name, judged_states
from dossier.domain.hashing import text_hash
from dossier.domain.judges import Calibration, withholding
from dossier.domain.pipeline import reads_reference
from dossier.domain.ports import ImagePart, Tracker
from dossier.domain.scoring import (
    check_same_documents,
    check_same_reference,
    compare_totals,
    describe_items,
    overall,
    per_field,
    unscored,
    weakest,
)
from dossier.domain.store import RUNS_ROOT
from dossier.domain.tracking import (
    NAMESPACE,
    comparison_description,
    eval_description,
    experiment_name,
    label_for,
    lost_documents,
    namespaced,
    not_compared_lines,
    not_scored_line,
)
from dossier.domain.tracking import settings as tracking_settings
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.store import SnapshotStore


def _version_experiment(workspace: Path, pipeline: str) -> str:
    """Where this pipeline's versions live: its **run** experiment (spec 013).

    Not the experiment of the command doing the registering. A version is
    produced by a run and merely measured by an eval, so it belongs beside the
    runs that produced it -- and an eval registering into its own experiment
    would give one pipeline two Models tabs that never meet. Spec 012 puts a
    dataset in the eval experiment on the same reasoning, from the other end.
    """
    return experiment_name(
        kind="run", pipeline=pipeline, gold="", environ=environment(workspace)
    )


def has_per_part(config) -> bool:
    """Whether this pipeline has a step that can answer from a picture (R7.20).

    A `per_part` step declaring an output is the only thing that can produce a
    `described` verdict (R3.12, R6.15). Asked here and handed to the domain,
    which decides what follows from it -- the loader asks the same question of
    the same shape when it refuses a missing bar.
    """
    return any(step.mode == "per_part" and step.output is not None for step in config.steps)


def scored_step(pipeline: str, config):
    """The one step whose output `eval` scores, or exit 2 saying how many declare one.

    Spec 007 scores "the output" against gold and does not yet say which step's
    output that is when several declare one. Refused rather than guessed,
    because a guess would report one step's scores as another's. `status` asks
    it too, before `eval` is run, and is refused in the same words (R17.6).
    """
    declaring = [step for step in config.steps if step.output is not None]
    if len(declaring) != 1:
        typer.echo(
            f"{pipeline}: {len(declaring)} steps declare an output; eval scores exactly one",
            err=True,
        )
        raise typer.Exit(code=2)
    return declaring[0]


def judge_gate(
    directory: Path, declaration: Path, pipeline_dir: Path, model: str, *, states=(GROUNDED,)
) -> tuple[dict[str, Calibration], dict[str, str]]:
    """Which judged fields may be reported, and why the rest may not (R7.15, R7.23).

    The reads are here -- the rubrics, the thresholds, each calibration file --
    and the decision is `withholding`'s, in the domain, so it is provable with
    a `Calibration` and four strings rather than a workspace.

    `states` are the grounding states this pipeline can answer a field in. Each
    is gated on its own calibration and its own bar, and a field is withheld
    whole if any of them fails: a field's percentage mixes verdicts of both
    kinds, so "0.82, of which the described half was never measured" is the
    number R7.5 refuses, arrived at more elaborately (R7.23).
    """
    rubrics = load_judge_rubrics(declaration)
    if not rubrics:
        return {}, {}

    # Absent is its own answer: a gold set with no judge.yaml has declared no
    # bar, and a field with no bar cannot be gated. Present and malformed still
    # raises, because that is a mistake somebody has to be told about (R7.13).
    declared = (directory / JUDGE_FILE).is_file()
    thresholds = load_judge_thresholds(directory) if declared else {}
    # The unsupported half's bar, where the gold set declares one (R7.30, R7.31).
    unsupported = load_unsupported_bars(directory) if declared else {}

    judges: dict[str, Calibration] = {}
    withheld: dict[str, str] = {}
    prompt = judge_prompt_hash()
    for field, named in sorted(rubrics.items()):
        for state in states:
            name = judge_name(field, state)
            measured = load_calibration(directory, name)
            if measured is not None:
                judges[name] = measured
            reason = withholding(
                measured,
                judge_model=model,
                rubric_hash=text_hash(pipeline_dir / named),
                prompt_hash=prompt,
                threshold=thresholds.get(field, {}).get(state),
                threshold_file=JUDGE_FILE,
                unsupported=unsupported.get(field, {}).get(state),
            )
            if reason is not None and field not in withheld:
                # The first failing state wins the message. Naming the state is
                # what makes the reason actionable: "never measured" sends
                # someone to `dossier calibrate`, and knowing it is the vision
                # judge that was never measured says which sample to write.
                withheld[field] = reason if state == GROUNDED else f"{state}: {reason}"

    return judges, withheld


def eval_(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
    compare: tuple[str, str] = typer.Option(
        (None, None), "--compare", help="Two run ids to compare, per field", metavar="A B"
    ),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Score a pipeline's latest run against a gold set, per field (spec 007).

    The run is reproduced from its own manifest and cache entries, exactly as a
    replay is, so scoring reads what the run produced and asks no model (R7.10).
    """
    workspace = Path.cwd()

    try:
        path = bootstrap.pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    step = scored_step(pipeline, config)
    kinds = load_fields(path.parent / step.output)

    # Before anything reads the gold set to score: an answer in a shape no run
    # can meet is the gold set's fault, and scoring against it would blame the
    # run. Here, so a comparison is refused as an eval is (R7.44).
    refused = gold_refusals(load_gold(workspace / gold), kinds)
    if refused:
        for line in refused:
            typer.echo(f"{pipeline}: {line}", err=True)
        raise typer.Exit(code=2)

    if compare[0] is not None:
        _compare_runs(
            workspace,
            pipeline,
            step=step.id,
            kinds=kinds,
            gold=gold,
            runs=compare,
            config=config,
            pipeline_dir=path.parent,
            declaration=path.parent / step.output,
            label=label,
        )
        return

    # After the compare branch, which records under its own kind: a comparison's
    # figures are deltas rather than accuracies, and an experiment should hold
    # runs comparable with one another (R10.2, R11.8). Before any scoring work,
    # so a server nobody can reach is refused now rather than after a
    # reproduction nobody can then inspect (R10.5).
    tracker, experiment = bootstrap.tracking_for(workspace, pipeline, kind="eval", gold=gold)
    # A version is part of the record, so it rides on the same switch (R10.1).
    versions = bootstrap.versions_for(workspace) if tracker is not None else None

    _, run_dir = latest_manifest(workspace / "runs", pipeline)
    if run_dir is None:
        typer.echo(
            f"{pipeline}: no run to score. Run `dossier run {pipeline}` first.", err=True
        )
        raise typer.Exit(code=2)
    manifest = Manifest.read(workspace / "runs" / run_dir / MANIFEST_NAME)

    scored, text, pages, failed = _reproduced(
        workspace, manifest, step.id, enums=load_enum_values(path.parent / step.output)
    )
    scores = score_run(report=scored, gold=load_gold(workspace / gold), kinds=kinds)

    judges, withheld = judge_gate(
        workspace / gold,
        path.parent / step.output,
        path.parent,
        config.model,
        states=judged_states(per_part=has_per_part(config)),
    )
    # The gold files are re-read as bytes instead of being serialised back from
    # what `load_gold` parsed: the hash has to move when any answer moves, and a
    # round trip through the model would hide a change that only altered how a
    # file was written (R11.3 row 2).
    gold_files = {p.name: p.read_bytes() for p in sorted((workspace / gold).glob("*.json"))}
    # From the moment the run may open to the moment it closes: a judge that
    # fails, or an interrupt, closes it FAILED rather than leaving it RUNNING
    # (R11.23). A tracker of None makes this nothing.
    with failed_if_stopped(tracker):
        if tracker is not None:
            # Asked for before the run opens, because whether the dataset is stale is
            # a tag, and a tag is set when a run starts (R11.7 row 2).
            # Not `scored`: that name holds the reproduced step result a few lines up.
            scored_hash = gold_set_hash(gold_files)
            published = _published_dataset(workspace, gold=gold)
            was = published.tags.get("dossier.gold_hash") if published is not None else None
            stale = was is not None and was != scored_hash
            # Opened before the judge is asked, so its traces sit inside the run
            # (R7.18 row 5); closed below with the figures the report printed.
            scored_version = start_eval(
                tracker,
                experiment=experiment or "",
                pipeline=pipeline,
                run_id=Path(run_dir).name,
                model=config.model,
                gold=gold,
                gold_files=gold_files,
                judges=judges,
                withheld=withheld,
                dataset_stale=stale,
                environ=environment(workspace),
                started=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
                label=label_for(label, environment(workspace)),
                plan=manifest.plan,
                dossier_version=manifest.dossier_version,
                scored_at=manifest.started_at.isoformat().replace("+00:00", "Z"),
                versions=versions,
                version_experiment=_version_experiment(workspace, pipeline),
                # Unverified and best-effort, as the run's is (R14.7): a server
                # with no prompt store costs the link and never the score.
                prompt_registry=bootstrap.prompt_registry_for(workspace),
                rubric_hashes={
                    field: text_hash(path.parent / named)
                    for field, named in load_judge_rubrics(path.parent / step.output).items()
                },
                prompt_prefix=environment(workspace).get(NAMESPACE, ""),
            )
            if published is not None:
                tracker.log_dataset(
                    name=published.name,
                    dataset_id=published.dataset_id,
                    digest=published.digest,
                )
            if stale:
                # Named, not fixed. Republishing here would have an eval quietly
                # mutate shared tracking state, and refusing would let a stale
                # dataset block a score computed entirely from local files (R12.4).
                typer.echo(
                    f"dataset {published.name} is stale: "
                    f"published {was[:8]}, scored {scored_hash[:8]}"
                )
                typer.echo("  run `dossier dataset publish` to refresh it")
        # The judge decides only what the deterministic scorers left, and only for
        # a field it may be quoted on: a withheld field is not judged at all, since
        # nothing is measured for a number nobody may print (R7.17).
        try:
            scores = judge_scores(
                scores,
                report=scored,
                judging=_judging(
                    workspace,
                    config=config,
                    pipeline_dir=path.parent,
                    declaration=path.parent / step.output,
                    # What the call was shown: the group (R7.33), and the
                    # reference documents it read (R7.34).
                    **_judged_evidence(step, manifest.plan, text),
                    pages=pages,
                    withheld=withheld,
                    run_id=run_dir,
                    tracker=tracker,
                ),
            )
        except bootstrap.MODEL_FAILURES as error:
            # A judge nobody can reach, said as `run` says a stage's (R9.20).
            typer.echo(f"{pipeline}: {error}", err=True)
            raise typer.Exit(code=2) from error
        totals = per_field(scores, declared=list(kinds))

        # The overall covers exactly the fields it reported. Folding a withheld field
        # back into the headline would hand over the number R7.5 just refused, in the
        # figure most people read first -- and would make the terminal disagree with
        # MLflow about one run, which spec 011 exists to prevent (R11.3 row 4).
        reported = [total for total in totals if total.field not in withheld]
        summed = overall(reported)
        if summed is not None:
            # The overall figure opens the report and never closes it: every field's
            # own line follows, so it can never be all that is printed (R7.2).
            # Counted in what was scored: for a `per_group` step, a group, which
            # is what its gold answer verifies (R7.32).
            # And what the run failed, counted here and not scored (R7.50 row 6):
            # 100% over three documents is not 100% of four (R7.52).
            typer.echo(
                f"{bootstrap.count(len(scores), scored.unit)} · "
                f"{bootstrap.count(len(reported), 'field')} · "
                f"overall {summed.percentage:.1f}%"
                + (f" · {len(failed)} failed" if failed else "")
            )
        lowest = weakest(reported)
        scored = {total.field: total for total in totals}
        # Walked over the *declared* fields, as `--compare` is (R7.8). A withheld
        # field whose every verdict went to the judge has nothing deterministic to
        # total, so a report written from the totals dropped it -- silently, and
        # exactly where the withholding matters most (R7.15 row 5).
        for field in kinds:
            if field in withheld:
                # Named, not omitted. A line that simply vanished would read as a
                # field nobody verified (R7.3 row 4), which is a different problem
                # and wants different work (R7.15).
                typer.echo(f"  {field:<18}     -- {withheld[field]}")
                continue
            total = scored.get(field)
            if total is None:
                # Nothing verified this field, so there is nothing to report and
                # nothing was refused. Absent is not withheld (R7.3 row 4).
                continue
            marker = "   <- weakest" if field in lowest else ""
            # A judged field says how many of its verdicts the judge decided. A
            # percentage over an unknown mix of abstention and judged verdicts is
            # the silent subset R7.17 replaced.
            judged = f"   ({total.judged} judged)" if kinds[field].needs_a_judge else ""
            # A list's items on the field's own line, beside the verdict they explain
            # and never in place of it (R7.43).
            items = f"   {describe_items(total)}" if total.items is not None else ""
            typer.echo(f"  {field:<18} {total.percentage:5.1f}%{judged}{items}{marker}")
            # What the percentage above does not say (R7.25). A field at 0.0% is a
            # prompt citing nothing locatable, or a model reading the wrong figure,
            # or a gold set that moved -- three different problems told apart by the
            # detail and not by reading the figure again (R7.4 row 2).
            #
            # In `scores` order, which is the run's document order, so two evals of
            # one run read identically (R0.4). Only the misses: a correct verdict
            # has no detail worth a line.
            for score in scores:
                for result in score.scored:
                    if result.field == field and not result.correct:
                        typer.echo(f"    {score.document:<14} {result.detail or 'incorrect'}")

        # Each document the run left unscored, named with its step and why,
        # beneath the fields it was not scored on (R7.52, R7.53, R6.31).
        for failed_at, document, reason in failed:
            typer.echo("  " + not_scored_line(step=failed_at, document=document, reason=reason))

        if tracker is not None:
            # The figures the lines above printed, recorded once rather than computed
            # a second way (R11.3).
            finish_eval(
                tracker,
                totals=totals,
                withheld=withheld,
                # Built from the figures the lines above printed, by the command that
                # printed them. MLflow is a second place to read them (R11.12).
                description=eval_description(
                    run_id=Path(run_dir).name,
                    pipeline=pipeline,
                    model=config.model,
                    pipeline_hash=manifest.plan.pipeline_hash,
                    gold=Path(gold).name,
                    gold_hash=gold_set_hash(gold_files),
                    documents=len(manifest.plan.documents),
                    totals=reported,
                    withheld=withheld,
                    left_out=len(failed),
                ),
                # The per-document lines printed just above, which nothing else
                # keeps (R11.14), the `not scored` lines among them (R11.31).
                detail=scores_artifact(scores, withheld=withheld, not_scored=failed),
                # The accuracy this eval measured, recorded against the version it
                # scored as well as against this run (R13.3).
                version_id=scored_version,
                # The count the headline printed (R7.52).
                failed=len(failed),
            )
            typer.echo(f"recorded to MLflow: {experiment}")


def _compare_runs(
    workspace: Path,
    pipeline: str,
    *,
    step: str,
    kinds: dict,
    gold: str,
    runs: tuple[str, str],
    config,
    pipeline_dir: Path,
    declaration: Path,
    label: str = "",
) -> None:
    """`dossier eval <pipeline> --gold <dir> --compare <a> <b>` (R7.8).

    The change gate. Each run is reproduced from its own manifest and cache, so
    the comparison asks no model, and both are scored against the same gold set.
    The documents are checked before anything is scored: a delta over different
    documents would report the documents' difference as the change's effect.
    """
    # Before the manifests are even read: with tracking on, a server nobody can
    # reach refuses the command now rather than after reproducing two runs
    # nobody can then inspect (R10.5).
    tracker, experiment = bootstrap.tracking_for(workspace, pipeline, kind="compare", gold=gold)

    model = config.model
    manifests: list[Manifest] = []
    for run in runs:
        path = workspace / "runs" / run / MANIFEST_NAME
        if not path.is_file():
            typer.echo(f"{pipeline}: no run {run!r} -- expected {path}", err=True)
            raise typer.Exit(code=2)
        manifest = Manifest.read(path)
        if manifest.plan.pipeline != pipeline:
            typer.echo(
                f"{pipeline}: run {run!r} is a run of {manifest.plan.pipeline!r}", err=True
            )
            raise typer.Exit(code=2)
        manifests.append(manifest)

    try:
        check_same_documents(
            *([document.key for document in m.plan.documents] for m in manifests), runs=runs
        )
        # And the same context: a procedure tightened between the runs moves the
        # fields that cite it, and the delta would credit the configuration
        # (R7.35).
        check_same_reference(manifests[0].plan, manifests[1].plan, runs=runs)
    except ValueError as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    gold_documents = load_gold(workspace / gold)
    # Gated exactly as an eval is (R7.17 row 7): the change gate is the place a
    # judge's number is most likely to be quoted, and a withheld field prints
    # its reason on both sides and no delta.
    _, withheld = judge_gate(
        workspace / gold,
        declaration,
        pipeline_dir,
        model,
        states=judged_states(per_part=has_per_part(config)),
    )
    totals: list[tuple] = []
    compared = next(s for s in config.steps if s.id == step)
    reproduced = [
        _reproduced(workspace, manifest, step, enums=load_enum_values(declaration))
        for manifest in manifests
    ]
    # A document either run left unscored is scored in neither (R7.54). Scored
    # over four in one run and three in the other, the failure read as each
    # field's regression, and the delta credited the configuration with it.
    left_out = {document for *_, failed in reproduced for _, document, _ in failed}
    kept = {key: answers for key, answers in gold_documents.items() if key not in left_out}
    for run, manifest, (scored, text, pages, _) in zip(
        runs, manifests, reproduced, strict=True
    ):
        try:
            scores = judge_scores(
                score_run(report=scored, gold=kept, kinds=kinds),
                report=scored,
                judging=_judging(
                    workspace,
                    config=config,
                    pipeline_dir=pipeline_dir,
                    declaration=declaration,
                    # As an eval judges it: against what the call was shown
                    # (R7.33, R7.34).
                    **_judged_evidence(compared, manifest.plan, text),
                    pages=pages,
                    withheld=withheld,
                    run_id=run,
                ),
            )
        except bootstrap.MODEL_FAILURES as error:
            # As an eval says it (R9.20). Nothing is recorded: a comparison
            # opens its run only once both sides are scored (R11.8 row 4).
            typer.echo(f"{pipeline}: {error}", err=True)
            raise typer.Exit(code=2) from error
        totals.append(per_field(scores, declared=list(kinds)))
    before, after = totals
    before = tuple(total for total in before if total.field not in withheld)
    after = tuple(total for total in after if total.field not in withheld)

    earlier, later = overall(before), overall(after)
    if earlier is not None and later is not None:
        # Opens the report and never closes it: the per-field rows follow, and a
        # regression hides behind a better overall figure unless they do (R7.8).
        typer.echo(
            f"compare {runs[0]} -> {runs[1]} · "
            f"{_compared_count(len(manifests[0].plan.documents), left=len(left_out))} · "
            f"overall {earlier.percentage:.1f}% -> {later.percentage:.1f}% "
            f"({later.percentage - earlier.percentage:+.1f})"
        )
    deltas = compare_totals(before, after)
    # Printed beneath the fields and recorded beneath the table, the same lines
    # (R7.55, R11.27).
    unscored_by_run = (reproduced[0][3], reproduced[1][3])
    named = not_compared_lines(unscored_by_run, runs=runs)
    if tracker is not None:
        # Recorded after the refusals above, so a comparison that was refused
        # records nothing: there is no delta, so there is no figure (R11.8 row 4).
        gold_files = {
            path.name: path.read_bytes() for path in sorted((workspace / gold).glob("*.json"))
        }
        published = _published_dataset(workspace, gold=gold)
        was = published.tags.get("dossier.gold_hash") if published is not None else None
        scored_hash = gold_set_hash(gold_files)
        record_comparison(
            tracker,
            experiment=experiment or "",
            pipeline=pipeline,
            dossier_version=version("dossier"),
            versions=bootstrap.versions_for(workspace),
            version_experiment=_version_experiment(workspace, pipeline),
            runs=runs,
            models=(manifests[0].plan.model, manifests[1].plan.model),
            gold=gold,
            gold_files=gold_files,
            rows=deltas,
            overalls=(earlier, later),
            dataset_stale=was is not None and was != scored_hash,
            environ=environment(workspace),
            started=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            label=label_for(label, environment(workspace)),
            plans=(manifests[0].plan, manifests[1].plan),
            description=comparison_description(
                runs=runs,
                pipeline=pipeline,
                models=(manifests[0].plan.model, manifests[1].plan.model),
                gold=Path(gold).name,
                gold_hash=scored_hash,
                documents=len(manifests[0].plan.documents),
                rows=deltas,
                overalls=(earlier, later),
                left_out=len(left_out),
                failed=unscored_by_run,
            ),
            detail=deltas_artifact(deltas, runs=runs, left_out=named),
            failed=(len(unscored_by_run[0]), len(unscored_by_run[1])),
            lost=[document for _, document, _ in lost_documents(unscored_by_run)],
            # Best-effort and unverified, as the eval's is (R14.11).
            prompt_registry=bootstrap.prompt_registry_for(workspace),
            rubric_hashes={
                field: text_hash(pipeline_dir / named)
                for field, named in load_judge_rubrics(declaration).items()
            },
            withheld=withheld,
            prompt_prefix=environment(workspace).get(NAMESPACE, ""),
        )
        if published is not None:
            # The same link an eval makes, on the other command that scores
            # against a gold set (R11.10).
            tracker.log_dataset(
                name=published.name, dataset_id=published.dataset_id, digest=published.digest
            )

    rows = {row.field: row for row in deltas}
    for field in kinds:
        if field in withheld:
            typer.echo(f"  {field:<18}     -- {withheld[field]}")
            continue
        row = rows.get(field)
        if row is None:
            continue
        was = f"{row.before.percentage:.1f}%" if row.before else "--"
        now = f"{row.after.percentage:.1f}%" if row.after else "--"
        moved = f"{row.delta:+.1f}" if row.delta is not None else "--"
        marker = "   <- regression" if row.regressed else ""
        typer.echo(f"  {row.field:<18} {was:>6} {now:>6} {moved:>6}{marker}")

    # What the comparison left out, beneath the fields it was left out of, and
    # never silently: a document either run failed is scored in neither (R7.55).
    for line in named:
        typer.echo("  " + line)

    if tracker is not None and experiment is not None:
        typer.echo(f"recorded to MLflow: {experiment}")


def _compared_count(pinned: int, *, left: int) -> str:
    """How many of the pinned documents a comparison scored (R7.54): `3 of 4 documents`."""
    if not left:
        return bootstrap.count(pinned, "document")
    return f"{pinned - left} of {bootstrap.count(pinned, 'document')}"


def _judging(
    workspace: Path,
    *,
    config,
    pipeline_dir: Path,
    declaration: Path,
    documents: Mapping[str, str],
    pages: Mapping[str, Sequence[ImagePart]] | None = None,
    withheld: Mapping[str, str],
    run_id: str,
    tracker: Tracker | None = None,
    context: str = "",
) -> Judging:
    """What the judge is asked with, for the fields R7.15 lets be reported (R7.17).

    The client is built on the first call and never before: a scoring pass
    with nothing deferred to a judge asks nothing and needs no endpoint
    (R7.10), and a cache that serves every verdict never builds one (R7.18).
    """
    rubrics = {
        field: (
            (pipeline_dir / named).read_text(encoding="utf-8"),
            text_hash(pipeline_dir / named),
        )
        for field, named in sorted(load_judge_rubrics(declaration).items())
        if field not in withheld
    }
    return Judging(
        model=bootstrap.BuiltOnFirstCall(config.model),
        cache=ArtifactCache(workspace, namespace="judge"),
        documents=documents,
        # What the run read as pictures, for the fields it answered from them
        # (R7.21). Empty for every pipeline that reads text, which is what the
        # default is for.
        parts=dict(pages or {}),
        context=context,
        rubrics=rubrics,
        judge_model=config.model,
        # What a judge's span may carry here, read as a stage's is (R10.8).
        capture=bootstrap.capture_for(workspace, config.name),
        run_id=run_id,
        dossier_version=version("dossier"),
        tracker=tracker,
    )


def _judged_evidence(step, plan, text: Mapping[str, str]) -> dict[str, object]:
    """What a judge of `step`'s answers is shown, from a run's reproduced text.

    The audited documents' evidence, as `judge_evidence` renders it, and the
    reference documents the step read, rendered for a field judged from its
    pages (R7.33, R7.34). Taken from the manifest's own lists, so a procedure
    re-synced since is not what the judge is shown (R4.16).
    """
    audited = {pinned.key: text[pinned.key] for pinned in plan.documents if pinned.key in text}
    reference = (
        {pinned.key: text[pinned.key] for pinned in plan.reference if pinned.key in text}
        if reads_reference(step.inputs)
        else {}
    )
    return {
        "documents": judge_evidence(audited, mode=step.mode, reference=reference),
        "context": reference_context(reference),
    }


def _reproduced(
    workspace: Path, manifest: Manifest, step: str, *, enums: Mapping[str, Sequence[str]]
):
    """One step's results as a past run produced them, served from its cache (R4.7).

    A run that cannot be reproduced stops the command by name. Recomputing it
    would score answers the run never gave. The converted text comes back too,
    and the pages beside it: a judge is shown the document as the run was
    (R7.17, R7.21), not as the workspace holds it now.
    """
    try:
        store = SnapshotStore(workspace)
        converted = ArtifactCache(workspace, namespace="convert")
        text = replayed_inputs(manifest, store=store, cache=converted)
        by_kind = replayed_parts(manifest, store=store, cache=converted)
        report = replay(
            manifest=manifest,
            document_text=text,
            # Without these a per_part run cannot be reproduced, and `eval`
            # scores a reproduction -- so it could score no such run at all
            # (R4.14).
            document_parts=by_kind,
            cache=ArtifactCache(workspace, namespace="stage"),
            # What the declaration allows each enum, so an answer outside it is
            # the finding it would be in a run, however long ago it was cached
            # (R6.26).
            enums={step: enums},
            # What the run failed, reproduced rather than looked for, so one
            # failed document no longer makes the whole run unscorable (R4.28,
            # R7.52).
            failures=recorded_failures(workspace / RUNS_ROOT / manifest.run_id),
        )
    except MissingFromReplay as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    # Flattened by document, because a judge is shown a document's pages and
    # does not care which kind produced them (R7.21). A document appearing under
    # two container kinds is not a shape any converter here produces.
    pages = {
        document: [part for _, part in entries]
        for entries in by_kind.values()
        for document, entries in entries.items()
    }
    scored = next(result for result in report.steps if result.step == step)
    # Not every failure: a document the scored step answered was scored, whatever
    # a step after it did, and one two steps failed is one document (R7.53).
    failed = unscored(
        [
            (done.step, result.document, result.error)
            for done in report.steps
            for result in done.failed
        ],
        steps=[done.step for done in report.steps],
        scored=step,
        answered={result.document for result in scored.results if not result.failed},
    )
    return scored, text, pages, failed


def _published_dataset(workspace: Path, *, gold: str) -> PublishedDataset | None:
    """The dataset published for this gold set, or `None` if there is not one.

    Best effort, and deliberately. A gold set nobody has published is not an error
    -- there is simply nothing to link -- and a dataset call that fails costs the
    eval nothing, because a lost record never changes a command's outcome (R10.6).
    What is never best effort is the score: that came from the files, and nothing
    read here can reach it (R12.4).
    """
    try:
        tracking = tracking_settings(environment(workspace))
        if tracking is None:
            return None
        # Under the name a publish would have sent (R10.13).
        namespace = environment(workspace).get(NAMESPACE, "")
        return bootstrap.build_dataset_registry(tracking).find(
            namespaced(Path(gold).name, namespace)
        )
    except Exception:
        # `TrackingUnavailable` included: an eval needs no dataset, so a server
        # that cannot hold one is no reason to refuse the command (R12.5 row 5).
        typer.echo("dataset not linked: MLflow could not be asked for it")
        return None
