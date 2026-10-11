"""Read back everything an MLflow server holds, and search it for the canaries.

    python mlflow_canaries.py http://127.0.0.1:5000

Four sections, each read straight off the server:

  run       every run in every experiment: its name, and each `masked/` metric
  dataset   every evaluation dataset -- a published gold set -- and each
            record's expectations
  traces    how many traces each experiment holds, and how many of them
            hold a placeholder: a search that finds no canary in a trace
            that recorded no text would prove nothing
  canaries  how many params, metrics, tags, traces and dataset records hold
            one of the seven canaries, and which ones do

A trace is searched whole: its tags, its request and response, and every
span's inputs, outputs and attributes. Read-only. It never writes to the
server.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import mlflow
from mlflow import MlflowClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canaries import held  # noqa: E402

# A placeholder as dossier writes one, such as `[PERSON_2]`: a trace that holds
# one recorded masked text, so a search of it for the canaries is not vacuous.
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z_]*_\d+\]")


def main(uri: str) -> None:
    client = MlflowClient(tracking_uri=uri)
    found: dict[str, list[str]] = {
        "params": [],
        "metrics": [],
        "tags": [],
        "traces": [],
        "dataset records": [],
    }
    counted = dict.fromkeys(found, 0)
    placed = 0

    experiments = sorted(client.search_experiments(), key=lambda e: e.name)
    for experiment in experiments:
        runs = client.search_runs(
            [experiment.experiment_id], order_by=["attributes.start_time ASC"]
        )
        for run in runs:
            masked = {
                k: int(v)
                for k, v in sorted(run.data.metrics.items())
                if k.startswith("masked/")
            }
            shown = " ".join(f"{k}={v}" for k, v in masked.items())
            print(f"run      {experiment.name:<40} {run.info.run_name:<44} {shown}".rstrip())
            for kind, values in (
                ("params", run.data.params),
                ("metrics", run.data.metrics),
                ("tags", run.data.tags),
            ):
                counted[kind] += len(values)
                for key, value in values.items():
                    if held(f"{key} {value}"):
                        found[kind].append(f"{run.info.run_name} {key}")

    # The datasets API reads the tracking URI MLflow was pointed at, not a client's.
    mlflow.set_tracking_uri(uri)
    from mlflow.genai.datasets import search_datasets

    for dataset in sorted(search_datasets(), key=lambda d: d.name):
        print(f"dataset  {dataset.name}")
        frame = dataset.to_df()
        for _, record in frame.sort_values(
            by="inputs", key=lambda column: column.map(json.dumps)
        ).iterrows():
            counted["dataset records"] += 1
            text = json.dumps(record.to_dict(), default=str, ensure_ascii=False)
            if held(text):
                found["dataset records"].append(f"{dataset.name} {record['inputs']}")
            expectations = json.dumps(
                record["expectations"], ensure_ascii=False, sort_keys=True
            )
            print(f"         {record['inputs']['document']}  {expectations}")

    for experiment in experiments:
        traces, token = [], None
        while True:
            page = client.search_traces(
                locations=[experiment.experiment_id], max_results=100, page_token=token
            )
            traces.extend(page)
            token = page.token
            if not token:
                break
        if traces:
            print(f"traces   {experiment.name:<40} {len(traces)}")
        for trace in traces:
            counted["traces"] += 1
            recorded = trace.to_json()
            placed += bool(PLACEHOLDER.search(recorded))
            if held(recorded):
                found["traces"].append(f"{experiment.name} {trace.info.trace_id}")

    print(f"         {placed} of {counted['traces']} traces hold a placeholder")
    print(
        "canaries "
        + " · ".join(f"{kind} {len(found[kind])} of {counted[kind]}" for kind in found)
    )
    for kind, where in found.items():
        for place in where:
            print(f"         {kind}: {place}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000")
