"""Print what MLflow holds about the latest `incident-review` run: task 7.

    # from the workspace, playground/work/22
    python ../../22-what-a-run-costs-and-how-fast-it-goes/resources/read_back.py \
        http://127.0.0.1:5001

Everything printed is something `dossier run` already printed or wrote to the
manifest. The record is a second place to read a figure, never a second way of
arriving at one (spec 011).
"""

from __future__ import annotations

import sys

import mlflow
from mlflow import MlflowClient

EXPERIMENT = "dossier-audit/incident-review/run"


def main(uri: str) -> None:
    client = MlflowClient(uri)
    mlflow.set_tracking_uri(uri)
    experiment = client.get_experiment_by_name(EXPERIMENT)
    run = client.search_runs(
        [experiment.experiment_id], order_by=["attributes.start_time DESC"], max_results=1
    )[0]

    print(f"name    {run.info.run_name}")
    print(f"label   {run.data.tags.get('dossier.label')}")
    for name in sorted(run.data.params):
        if name == "concurrency" or name.startswith("model"):
            print(f"param   {name} = {run.data.params[name]}")
    for name in sorted(run.data.metrics):
        if name.startswith("tokens"):
            print(f"metric  {name} = {run.data.metrics[name]:g}")

    traces = mlflow.search_traces(
        locations=[experiment.experiment_id], run_id=run.info.run_id, return_type="list"
    )
    for trace in sorted(traces, key=lambda each: each.info.tags.get("mlflow.traceName", "")):
        for span in trace.data.spans:
            usage = span.attributes.get("mlflow.chat.tokenUsage")
            if usage:
                print(
                    f"span    {trace.info.tags.get('mlflow.traceName')}  "
                    f"{span.attributes.get('dossier.model')}  "
                    f"in {usage['input_tokens']} out {usage['output_tokens']}"
                )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5001")
