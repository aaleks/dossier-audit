"""`dossier dataset publish` (spec 012)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer

from dossier.application.datasets import EmptyGoldSet, publish_gold
from dossier.application.masking import MASK, MASK_VALUES, mask_texts
from dossier.cli import bootstrap
from dossier.cli.calibrate import held_content
from dossier.config.environment import environment
from dossier.config.load import ConfigError, load_fields, load_pipeline
from dossier.domain.gold import GoldDocument
from dossier.domain.masking import (
    NOT_CLIENT_DATA,
    MaskerUnavailable,
    Masking,
    language_of,
    mask_like,
)
from dossier.domain.pipeline import PipelineConfig
from dossier.domain.ports import Masker
from dossier.domain.sync import State
from dossier.domain.tracking import NAMESPACE, experiment_name, namespace
from dossier.domain.tracking import settings as tracking_settings
from dossier.infrastructure.cache import ArtifactCache
from dossier.infrastructure.ledger import Ledger
from dossier.infrastructure.models.registry import available_providers
from dossier.infrastructure.tracking.mlflow import TrackingUnavailable

dataset_app = typer.Typer(
    add_completion=False,
    help="Publish a gold set to MLflow as an evaluation dataset (spec 012).",
)


@dataset_app.command("publish")
def dataset_publish(
    pipeline: str = typer.Argument(..., help="Pipeline name under pipelines/"),
    gold: str = typer.Option(..., "--gold", help="Gold set directory", metavar="DIR"),
) -> None:
    """Publish a gold set as the MLflow evaluation dataset named after it (R12.1).

    Reads `gold/` and sends; asks no model, reproduces no run, and writes nothing
    to disk. The dataset lands in the experiment an eval over this gold set
    records to (R10.2), so it sits beside the runs measured against it.
    """
    workspace = Path.cwd()
    environ = environment(workspace)

    try:
        path = bootstrap.pipeline_path(workspace, pipeline)
        config = load_pipeline(path, providers=available_providers())
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    # A masked pipeline's answers are masked before they are sent, and one
    # that cannot mask is refused before anything is (R21.7, R21.24).
    masking, masker = bootstrap.masking_for(pipeline, config, path)

    # The switch, the template and the server, in the order a person would fix
    # them and all before anything is sent (R12.5). Unlike every other command,
    # this one has nothing to do with tracking off: its whole output is the
    # record, so off is a refusal rather than a quiet no-op (R12.5 row 1).
    try:
        tracking = tracking_settings(environ)
        if tracking is None:
            raise ValueError(
                "publishing a dataset needs tracking on: set DOSSIER_MLFLOW_ENABLED=true "
                "and DOSSIER_MLFLOW_TRACKING_URI. A dataset is published to MLflow and "
                "nowhere else"
            )
        experiment = experiment_name(kind="eval", pipeline=pipeline, gold=gold, environ=environ)
        # Before anything is sent, and although a dataset name alone would take a
        # `/`: one namespace goes in front of every published name (R10.14 row 5).
        namespace(environ)
        registry = bootstrap.build_dataset_registry(tracking)
    except (ValueError, TrackingUnavailable) as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error

    directory = workspace / gold
    if not directory.is_dir():
        # A path that is not there and a directory holding no answers want
        # different fixes -- a corrected path, or a reviewer -- so they do not
        # share a message. A mistyped `--gold` is the likelier of the two, and
        # publishing an empty dataset under the mistyped name would be worse than
        # refusing and harder to notice.
        typer.echo(f"{pipeline}: no gold set at {gold}", err=True)
        raise typer.Exit(code=2)

    prepare = (
        None
        if masking is None or masker is None
        else _masked_answers(workspace, pipeline, config, path, masking=masking, masker=masker)
    )
    try:
        published = publish_gold(
            registry,
            gold=directory,
            experiment=experiment,
            snapshots=_held_snapshots(workspace),
            namespace=environ.get(NAMESPACE, ""),
            prepare=prepare,
        )
    except EmptyGoldSet as error:
        # Named as the person typed it. `EmptyGoldSet` carries the resolved path,
        # and an absolute one with this machine's separators in it is noise around
        # the one word they need to see (R12.1 row 3).
        typer.echo(f"{pipeline}: {gold}: no verified answers to publish", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"{published.name} · {bootstrap.count(published.records, 'record')} · "
        f"digest {published.digest}"
    )
    # The id MLflow assigned, because it is what addresses the dataset in the
    # UI and in the API. Printed and never written: a file holding it would
    # make a manifest or a cache entry depend on what a server said
    # (R12.4 row 3).
    typer.echo(f"published to MLflow: {experiment} ({published.dataset_id})")


def _held_snapshots(workspace: Path) -> dict[str, str]:
    """Every held document's snapshot address, by document key (R12.2 row 1).

    Provenance for the answers rather than a precondition for them: a gold set
    published before the first sync finds nothing here, and publishes anyway
    (R12.2 row 3).
    """
    with Ledger(workspace) as ledger:
        return {
            row.key: row.snapshot
            for source in ledger.sources()
            for row in ledger.rows(source)
            if row.state is not State.TOMBSTONED
        }


def _masked_answers(
    workspace: Path,
    pipeline: str,
    config: PipelineConfig,
    path: Path,
    *,
    masking: Masking,
    masker: Masker,
) -> Callable[[GoldDocument], GoldDocument]:
    """How a masked pipeline's gold document is published: each answer masked (R21.24).

    By its document's numbering, from the document's masked view, so the
    client is the same placeholder in the expectation as in the run's answer
    an eval compares it with (R21.22, R21.23). The views are made from what is
    held now, so a gold set can be published before any run. An answer of a
    kind that is never client data -- an enum, a number, a date -- is sent as
    written. A document that cannot be masked stops the publish: nothing is
    sent unmasked instead.
    """
    documents, _, _ = held_content(workspace, config)
    try:
        shown = mask_texts(
            documents,
            masking=masking,
            masker=masker,
            cache=ArtifactCache(workspace, namespace=MASK),
            values=ArtifactCache(workspace, namespace=MASK_VALUES),
            run_id=f"dataset {datetime.now(UTC):%Y%m%dT%H%M%SZ}",
            dossier_version=version("dossier"),
        )
    except MaskerUnavailable as error:
        typer.echo(f"{pipeline}: {error}", err=True)
        raise typer.Exit(code=2) from error
    if shown.failed:
        for key, reason in sorted(shown.failed.items()):
            typer.echo(f"  {key} could not be masked: {reason}", err=True)
        typer.echo(
            f"{pipeline}: nothing is published while a document is left unmasked", err=True
        )
        raise typer.Exit(code=2)
    declaring = [step for step in config.steps if step.output is not None]
    kinds = load_fields(path.parent / declaring[0].output) if len(declaring) == 1 else {}

    def masked(value: str, mapping: dict[str, str]) -> str:
        language = language_of(value, masking.declaration.languages)
        return mask_like(value, masker.detect(value, language=language), masking, mapping)

    def prepare(document: GoldDocument) -> GoldDocument:
        mapping = shown.mappings.get(document.document, {})
        fields: dict[str, dict] = {}
        for name, answer in document.fields.items():
            value = answer.get("value")
            if kinds.get(name) in NOT_CLIENT_DATA:
                fields[name] = answer
            elif isinstance(value, str):
                fields[name] = {**answer, "value": masked(value, mapping)}
            elif isinstance(value, list):
                fields[name] = {
                    **answer,
                    "value": [
                        masked(item, mapping) if isinstance(item, str) else item
                        for item in value
                    ],
                }
            else:
                fields[name] = answer
        return document.model_copy(update={"fields": fields})

    return prepare
