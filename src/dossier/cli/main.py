"""The `dossier` command line (specs 002, 003).

The only layer that exits the interpreter, and the only place that knows which
concrete connector, store and ledger are in play -- everything below takes them
as arguments. This module is the entry point and the index: each command lives
in a module of its own, and `bootstrap` builds what they are handed.
"""

from __future__ import annotations

import typer

from dossier.cli.calibrate import calibrate
from dossier.cli.convert import convert
from dossier.cli.dataset import dataset_app
from dossier.cli.eval import eval_
from dossier.cli.gc import gc
from dossier.cli.prompts import prompts_app
from dossier.cli.review import review_app
from dossier.cli.run import run
from dossier.cli.status import status
from dossier.cli.sync import sync

app = typer.Typer(add_completion=False)


@app.callback()
def main() -> None:
    """Collect documents, audit them, and prove the result.

    A callback is declared so that `sync` stays a sub-command. Typer collapses
    a single-command app into a bare invocation, and `dossier <pipeline>` is
    not the interface the specs describe -- `run` and `eval` join it later.
    """


# In the order `dossier --help` lists them.
app.command()(sync)
app.command()(run)
app.command()(convert)
app.command()(calibrate)
app.command("eval")(eval_)
app.command()(gc)
app.command()(status)
app.add_typer(dataset_app, name="dataset")
app.add_typer(review_app, name="review")
app.add_typer(prompts_app, name="prompts")
