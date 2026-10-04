"""`dossier calibrate`: a judge measured against the humans who scored its sample (spec 007)."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer

from dossier.application.convert import convert_source
from dossier.application.eval import FieldSample, calibrate_fields
from dossier.application.masking import MASK, MASK_VALUES, mask_texts
from dossier.application.run import judge_evidence, reference_context
from dossier.cli import bootstrap
from dossier.cli.convert import exit_if_unconvertible, read_holdings
from dossier.cli.eval import has_per_part
from dossier.config.environment import environment
from dossier.config.load import (
    ConfigError,
    load_calibration_sample,
    load_judge_rubrics,
    load_pipeline,
    load_sources,
)
from dossier.domain.conversion import PART_TYPE, NoConverter, unpack_parts
from dossier.domain.gold import CalibrationCase
from dossier.domain.grounding import judge_name, judged_states
from dossier.domain.hashing import text_hash
from dossier.domain.judges import NotCalibrated
from dossier.domain.masking import MaskerUnavailable, Masking, language_of, mask_like
from dossier.domain.pipeline import reads_reference
from dossier.domain.ports import ImagePart, Masker
from dossier.domain.tracking import NAMESPACE, calibration_lines, label_for
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.connectors.registry import declared_keys
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.store import SnapshotStore


def held_content(
    workspace: Path, config
) -> tuple[dict[str, str], dict[str, list[ImagePart]], dict[str, str]]:
    """The converted text and the pages of every document the workspace holds (R7.14).

    The same path `dossier convert` walks -- ledger rows, then conversion -- and
    for a reason worth stating: a calibration is about a judge and a rubric, not
    about any past run, so there is no manifest to reproduce and nothing to
    replay. What the judge is shown is what the workspace holds today.
    """
    try:
        declared = {
            source.id: source
            for source in load_sources(workspace / "sources.yaml", connectors=declared_keys())
        }
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    converters = bootstrap.converters_for(workspace)
    store = SnapshotStore(workspace)
    cache = ArtifactCache(workspace, namespace="convert")

    text: dict[str, str] = {}
    pages: dict[str, list[ImagePart]] = {}
    # The `reference:` sources' text as well, apart: a judged field of a step
    # reading them is measured against them too (R7.34).
    reference: dict[str, str] = {}
    with Ledger(workspace) as ledger:
        holdings = read_holdings(ledger, config.synced_sources, declared)
        exit_if_unconvertible(holdings, converters)
        for name, source, held in holdings:
            try:
                report = convert_source(
                    source_id=name,
                    documents=held,
                    kinds=source.convert,
                    converters=converters,
                    store=store,
                    cache=cache,
                )
            except NoConverter as error:
                typer.echo(str(error), err=True)
                raise typer.Exit(code=2) from error
            text.update(report.text)
            if name in config.reference:
                reference.update(report.text)
            # The pages behind every container this source produced, for the
            # judge a described field is measured against (R7.21, R7.22). Read
            # from the same conversion the text came from, so the judge is
            # shown what a run would show it.
            for kind in {a.kind for d in report.documents for a in d.artifacts}:
                for key, payload in report.content(kind).items():
                    try:
                        unpacked = unpack_parts(payload)
                    except ValueError:
                        continue
                    pages[key] = [
                        ImagePart(media_type=PART_TYPE, data=part) for part in unpacked
                    ]
    return text, pages, reference


def calibrate(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
    label: str = typer.Option(
        "", "--label", help="A name for this record, in MLflow (R10.11).", metavar="NAME"
    ),
) -> None:
    """Measure each judged field's judge against the gold set's sample (R7.14).

    Writes what it measured to `<gold>/calibrations/<field>.json`. It never
    touches `<gold>/judge.yaml`: the bar is agreed by a person, and a run able to
    move the bar it is judged against would be a judge grading its own paper
    (R7.20).
    """
    workspace = Path.cwd()

    try:
        path = bootstrap.pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    declaring = [step for step in config.steps if step.output is not None]
    if len(declaring) != 1:
        # Spec 007 scores "the output" and does not yet say which step's output
        # that is when several declare one. Refused rather than guessed, as
        # `eval` refuses it.
        typer.echo(
            f"{pipeline}: {len(declaring)} steps declare an output; "
            "calibrate reads exactly one",
            err=True,
        )
        raise typer.Exit(code=2)
    declaration = path.parent / declaring[0].output

    try:
        rubrics = load_judge_rubrics(declaration)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    if not rubrics:
        typer.echo(
            f"{pipeline}: no field is judged by a rubric, so none can be calibrated", err=True
        )
        raise typer.Exit(code=2)

    # Before any measuring work, so a server nobody can reach is refused now
    # rather than after twenty judge calls nobody can then inspect (R10.5).
    tracker, experiment = bootstrap.tracking_for(
        workspace, pipeline, kind="calibrate", gold=gold
    )

    # A masked pipeline's judge is shown what its stages are shown (R21.20),
    # and one that cannot mask is refused before any judge is asked (R21.7).
    masking, masker = bootstrap.masking_for(pipeline, config, path)

    directory = workspace / gold
    documents, held_parts, held_reference = held_content(workspace, config)
    mappings: dict[str, dict[str, str]] = {}
    if masking is not None and masker is not None:
        documents, held_reference, mappings = _masked_content(
            workspace, pipeline, documents, held_reference, masking=masking, masker=masker
        )
    # A case is judged against what the step's call was shown, as an eval's
    # question about the same answer is: every member of a group (R7.33),
    # and every reference document the step read (R7.34).
    reference = held_reference if reads_reference(declaring[0].inputs) else {}
    documents = judge_evidence(documents, mode=declaring[0].mode, reference=reference)

    # One judge per state the pipeline can answer a field in, each measured on
    # its own sample and recorded beside the other (R7.22).
    states = judged_states(per_part=has_per_part(config))

    samples: dict[str, FieldSample] = {}
    for field, named in sorted(rubrics.items()):
        # Against the pipeline's own directory, as `prompts/` and `output` are:
        # the declaration lives in `schemas/` and the rubric beside it in
        # `rubrics/`, so resolving against the declaration would look for
        # `schemas/rubrics/...`.
        rubric = path.parent / named
        for state in states:
            name = judge_name(field, state)
            try:
                cases = load_calibration_sample(directory, name)
                if masking is not None and masker is not None:
                    cases = _masked_cases(cases, mappings, masking=masking, masker=masker)
                samples[name] = FieldSample(
                    cases=cases,
                    rubric=rubric.read_text(encoding="utf-8"),
                    rubric_hash=text_hash(rubric),
                    field=field,
                    state=state,
                )
            except ConfigError as error:
                typer.echo(f"{name}: {error}", err=True)
                raise typer.Exit(code=2) from error

    try:
        measured = calibrate_fields(
            bootstrap.build_model_client(config.model),
            directory=directory,
            samples=samples,
            documents=documents,
            judge_model=config.model,
            parts=held_parts,
            context=reference_context(reference),
            tracker=tracker,
            experiment=experiment or "",
            environ=environment(workspace),
            started=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            label=label_for(label, environment(workspace)),
            pipeline=pipeline,
            dossier_version=version("dossier"),
            # Best-effort, as the eval's is (R14.9): a server with no prompt
            # store costs the link and never the measurement.
            prompt_registry=bootstrap.prompt_registry_for(workspace)
            if tracker is not None
            else None,
            prompt_prefix=environment(workspace).get(NAMESPACE, ""),
            # As bytes, as `record_eval` reads them: the hash has to move when
            # any answer moves (R11.3 row 2).
            gold_files={
                gold_file.name: gold_file.read_bytes()
                for gold_file in sorted(directory.glob("*.json"))
            },
        )
    except NotCalibrated as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    except bootstrap.MODEL_FAILURES as error:
        # The judge is a model like any stage's, and fails like one: in the line
        # `run` prints, not a traceback (R9.25).
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    for field, calibration in sorted(measured.items()):
        # In the domain for the reason the run's step line is: `calibrate_fields`
        # put these same lines on the record it closed (R11.17, R7.29).
        for line in calibration_lines(field, calibration):
            typer.echo(line)
    if tracker is not None:
        typer.echo(f"recorded to MLflow: {experiment}")


def _masked_content(
    workspace: Path,
    pipeline: str,
    documents: dict[str, str],
    reference: dict[str, str],
    *,
    masking: Masking,
    masker: Masker,
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, str]]]:
    """The documents and procedures as a masked pipeline's judge is shown them (R21.20).

    Each masked view comes with its mapping, which each candidate about it is
    masked with (R21.22). A document that cannot be masked stops the
    calibration: its cases cannot be judged unmasked, and a sample measured
    without them would be another sample.
    """

    def masked(texts: dict[str, str]):
        return mask_texts(
            texts,
            masking=masking,
            masker=masker,
            cache=ArtifactCache(workspace, namespace=MASK),
            values=ArtifactCache(workspace, namespace=MASK_VALUES),
            run_id=f"calibrate {datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            dossier_version=version("dossier"),
        )

    try:
        shown, context = masked(documents), masked(reference)
    except MaskerUnavailable as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
    failed = {**shown.failed, **context.failed}
    if failed:
        for key, reason in sorted(failed.items()):
            typer.echo(f"  {key} could not be masked: {reason}", err=True)
        typer.echo(f"{pipeline}: nothing is calibrated on a document left unmasked", err=True)
        raise typer.Exit(code=2)
    return shown.texts, context.texts, shown.mappings


def _masked_cases(
    cases: tuple[CalibrationCase, ...],
    mappings: dict[str, dict[str, str]],
    *,
    masking: Masking,
    masker: Masker,
) -> tuple[CalibrationCase, ...]:
    """Each candidate masked with its document's numbering (R21.20, R21.22)."""
    masked: list[CalibrationCase] = []
    for case in cases:
        language = language_of(case.answer, masking.declaration.languages)
        try:
            found = masker.detect(case.answer, language=language)
        except MaskerUnavailable as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=2) from error
        answer = mask_like(case.answer, found, masking, mappings.get(case.document, {}))
        masked.append(case.model_copy(update={"answer": answer}))
    return tuple(masked)
