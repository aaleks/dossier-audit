"""Print what an MLflow server holds about prompts, and who links them.

    python links.py http://127.0.0.1:5113

Four sections, each read straight off the server:

  prompt   every version of every prompt, with the hash `dossier` tagged it with
  dataset  every evaluation dataset -- a published gold set (spec 012)
  run      every run in every experiment, and the prompt versions it links
  version  every logged model -- a pipeline version (spec 013) -- and its prompts

A link is the `mlflow.linkedPrompts` tag MLflow keeps on a run and on a logged
model. The UI renders it; this prints it, so a checkpoint can be read without
knowing where a given MLflow release puts it on the page.

Read-only. It never writes to the server.
"""

from __future__ import annotations

import json
import sys

import mlflow
from mlflow import MlflowClient


def _links(tags: dict[str, str]) -> list[str]:
    held = json.loads(tags.get("mlflow.linkedPrompts", "[]"))
    return [f"{link['name']} v{link['version']}" for link in held]


def main(uri: str) -> None:
    client = MlflowClient(tracking_uri=uri)

    for prompt in sorted(client.search_prompts(), key=lambda p: p.name):
        versions = client.search_prompt_versions(prompt.name)
        for version in sorted(versions, key=lambda v: int(v.version)):
            digest = (version.tags or {}).get("dossier.prompt_hash", "")
            print(f"prompt   {version.name:<42} v{version.version}  {digest[:8]}")

    # The datasets API reads the tracking URI MLflow was pointed at, not a client's.
    mlflow.set_tracking_uri(uri)
    from mlflow.genai.datasets import search_datasets

    for dataset in sorted(search_datasets(), key=lambda d: d.name):
        print(f"dataset  {dataset.name}")

    experiments = sorted(client.search_experiments(), key=lambda e: e.name)
    for experiment in experiments:
        runs = client.search_runs(
            [experiment.experiment_id], order_by=["attributes.start_time ASC"]
        )
        for run in runs:
            linked = ", ".join(_links(run.data.tags)) or "-"
            print(f"run      {experiment.name:<46} {run.info.run_name:<58} {linked}")

    for experiment in experiments:
        models = client.search_logged_models(
            experiment_ids=[experiment.experiment_id],
            order_by=[{"field_name": "creation_time", "ascending": True}],
        )
        for model in models:
            linked = ", ".join(_links(model.tags)) or "-"
            print(f"version  {model.model_id}  {linked}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5113")
