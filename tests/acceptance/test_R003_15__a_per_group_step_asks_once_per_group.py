"""R3.15 — a `per_group` step asks the model once per group, and a document's
group is its key up to the first `/`.

The second use case (`docs/second-use-case.md`, finding 1): a supplier contract
is a master agreement and its amendments, kept in a folder named for the
contract, and no single file answers a question about it. Run through the CLI
because every layer has to agree for it to be true: the folder source keys each
file by its path, the plan fans the step out over groups rather than documents,
each call is handed exactly its group's members, and each answer lands under the
group's name.

The members are markdown rather than the PDFs `_fixtures.md` names. The rule is
about keys, not formats, and `ACME-2024/master.md` is keyed exactly as
`ACME-2024/master.pdf` would be; a PDF would only add a converter to the path
between the file and the key. The model is a fake that answers every call and
records which documents each one was shown, so the call count and each call's
members are both assertions (R0.1).

The rows about the key alone -- an attachment under its issue (row 3), a folder
two levels deep (row 5), a page's PDF export (row 9) -- are decisions of
`group_of`, proved in `tests/unit/`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.acceptance.conftest import URI, _cli
from tests.fakes import FakeTracker, register_connector
from tests.pipelines import write_pipeline
from tests.scoring_example import FIELDS, SOURCE_TYPE, IssueTracker, abstains

PIPELINE = "contract-renewal"
CONTRACTS = {
    "ACME-2024/master.md": "# ACME master agreement\n\nLiability is capped at EUR 2,000,000.\n",
    "ACME-2024/amendment-1.md": "# Amendment 1\n\nThe invoicing address changes.\n",
    "ACME-2024/amendment-3.md": "# Amendment 3\n\nThe term is extended to 2027-03-31.\n",
    "GLOBEX-2023/master.md": "# GLOBEX master agreement\n\nThe term ends 2026-12-31.\n",
}
ACME = ["ACME-2024/amendment-1.md", "ACME-2024/amendment-3.md", "ACME-2024/master.md"]
MEMBER = re.compile(r'<document key="([^"]+)">')


class Model:
    """Answers every call, and remembers which documents each call was shown.

    An answer abstains on every field: what is extracted is not this rule's
    business, which calls are made and what each is handed is. A call shown a
    document in `refusing` is answered with something no schema accepts, so the
    call fails validation twice (R6.2) and its unit fails alone (R6.9).
    """

    model_id = "anthropic:claude-sonnet-4-5-20250929"

    def __init__(self, *, refusing: frozenset[str] = frozenset()) -> None:
        self.refusing = refusing
        self.calls: list[list[str]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, prompt: str, *, schema: dict | None = None, parts=()) -> str:
        shown = MEMBER.findall(prompt)
        self.calls.append(shown)
        if self.refusing & set(shown):
            return "not an answer"
        return json.dumps({"document": shown[0], "fields": [abstains(f) for f in FIELDS]})


def _contracts(
    workspace: Path, monkeypatch, *, mode: str = "per_group", files=CONTRACTS
) -> Path:
    """A folder of contracts, one subfolder per contract, and a step over them."""
    for key, text in files.items():
        path = workspace / "inbox" / "contracts" / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (workspace / "sources.yaml").write_text(
        "sources:\n  - id: contracts\n    type: folder\n    path: inbox/contracts/\n",
        encoding="utf-8",
    )
    write_pipeline(workspace, name=PIPELINE, sources=["contracts"], modes={"extract": mode})
    synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
    assert synced.exit_code == 0, synced.output
    return workspace


def _serve(monkeypatch, model: Model) -> Model:
    import dossier.cli.main as cli

    monkeypatch.setattr(cli, "build_model_client", lambda model_id: model)
    return model


def _run_dir(workspace: Path) -> Path:
    (run,) = [path for path in (workspace / "runs").iterdir() if path.is_dir()]
    return run


class TestAPerGroupStepAsksOncePerGroup:
    """R3.15 — one call per group; a document's group is its key up to the first `/`."""

    def test_four_documents_that_are_two_contracts_are_two_calls(
        self, workspace: Path, monkeypatch
    ):
        """Row 1: the one where four documents are two contracts.

        Two calls, and two answers named for the contracts -- each saying its
        contract as `document`, as a `per_file` answer says its document's key.
        The step line counts what it asked about.
        """
        _contracts(workspace, monkeypatch)
        model = _serve(monkeypatch, Model())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert model.call_count == 2
        extract = _run_dir(workspace) / "extract"
        assert sorted(
            path.name for path in extract.glob("*.json") if not path.name.endswith(".meta.json")
        ) == [
            "ACME-2024.json",
            "GLOBEX-2023.json",
        ]
        for group in ("ACME-2024", "GLOBEX-2023"):
            written = json.loads((extract / f"{group}.json").read_text(encoding="utf-8"))
            assert written["document"] == group
        assert any(
            line.strip().startswith("extract: 2 group(s) · 0 from cache · 0 failed")
            for line in result.output.splitlines()
        ), result.output

    def test_a_groups_call_holds_its_members_in_key_order_and_nothing_else(
        self, workspace: Path, monkeypatch
    ):
        """Row 2: the one where the call shows every member under its own key.

        In key order, so the same members make the same prompt and the same key
        (R0.4), and without the other contract: a group's call is an aggregate
        call limited to the group.
        """
        _contracts(workspace, monkeypatch)
        model = _serve(monkeypatch, Model())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert sorted(model.calls) == [ACME, ["GLOBEX-2023/master.md"]]

    def test_an_issue_and_a_file_filed_under_it_elsewhere_are_one_group(
        self, workspace: Path, monkeypatch
    ):
        """Row 4: the one where a group spans two sources.

        `INC-4821` from the issue tracker, and a postmortem somebody dropped in a
        folder under `INC-4821/`. Keys are unique across sources (R4.10), so a
        group -- a prefix of keys -- can take members from both.
        """
        folder = workspace / "inbox" / "dropped" / "INC-4821"
        folder.mkdir(parents=True)
        (folder / "postmortem.md").write_text("# Postmortem\n\nThe cert expired.\n", "utf-8")
        (workspace / "sources.yaml").write_text(
            "sources:\n"
            f"  - id: incidents-jira\n    type: {SOURCE_TYPE}\n"
            "  - id: incidents-dropped\n    type: folder\n    path: inbox/dropped/\n",
            encoding="utf-8",
        )
        register_connector(
            monkeypatch,
            SOURCE_TYPE,
            lambda config, *, workspace: IssueTracker({"INC-4821": "# INC-4821\n\nDown.\n"}),
        )
        write_pipeline(
            workspace,
            name=PIPELINE,
            sources=["incidents-jira", "incidents-dropped"],
            modes={"extract": "per_group"},
        )
        synced = _cli(workspace, monkeypatch, "sync", PIPELINE)
        assert synced.exit_code == 0, synced.output
        model = _serve(monkeypatch, Model())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert model.calls == [["INC-4821", "INC-4821/postmortem.md"]]

    def test_a_group_that_fails_fails_alone(self, workspace: Path, monkeypatch):
        """Row 6: the one where one contract's answer is refused twice.

        The group is the unit of failure as it is of the key: GLOBEX fails,
        ACME is written, and the run goes on (R6.9).
        """
        _contracts(workspace, monkeypatch)
        _serve(monkeypatch, Model(refusing=frozenset({"GLOBEX-2023/master.md"})))

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert any(
            line.strip().startswith("extract: 2 group(s) · 0 from cache · 1 failed")
            for line in result.output.splitlines()
        ), result.output
        extract = _run_dir(workspace) / "extract"
        assert (extract / "ACME-2024.json").is_file()
        assert not (extract / "GLOBEX-2023.json").exists()

    def test_a_tracked_run_has_one_trace_per_group(self, workspace: Path, monkeypatch):
        """Row 7: the one where MLflow shows contracts, not files (R11.1).

        One trace per unit of work, named for the group, as a `per_file` trace
        is named for its document.
        """
        tracker = FakeTracker()
        monkeypatch.setenv("DOSSIER_MLFLOW_ENABLED", "true")
        monkeypatch.setenv("DOSSIER_MLFLOW_TRACKING_URI", URI)
        import dossier.cli.main as cli

        monkeypatch.setattr(cli, "build_tracker", lambda settings: tracker, raising=False)
        _contracts(workspace, monkeypatch)
        _serve(monkeypatch, Model())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        run = tracker.runs[-1]
        assert sorted(trace.name for trace in run.traces) == [
            "extract · ACME-2024",
            "extract · GLOBEX-2023",
        ]

    def test_on_a_flat_folder_per_group_asks_what_per_file_asks(
        self, workspace: Path, monkeypatch
    ):
        """Row 8, a counter-example: the one with nothing to group.

        A key with no `/` is a group of one, named by the key. On a flat folder
        the step asks one call per file, each shown that file alone.
        """
        flat = {"PLAY-1001.md": "# PLAY-1001\n\nA note.\n", "PLAY-1002.md": "# PLAY-1002\n"}
        _contracts(workspace, monkeypatch, files=flat)
        model = _serve(monkeypatch, Model())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert sorted(model.calls) == [["PLAY-1001.md"], ["PLAY-1002.md"]]
        extract = _run_dir(workspace) / "extract"
        assert sorted(
            path.name for path in extract.glob("*.json") if not path.name.endswith(".meta.json")
        ) == [
            "PLAY-1001.md.json",
            "PLAY-1002.md.json",
        ]

    def test_a_per_file_step_over_the_same_contracts_is_unchanged(
        self, workspace: Path, monkeypatch
    ):
        """Row 10, a counter-example: the one where the step did not ask for groups.

        Grouping is a step's choice. The same four documents under `per_file`
        are four calls, each shown one document, exactly as before this rule.
        """
        _contracts(workspace, monkeypatch, mode="per_file")
        model = _serve(monkeypatch, Model())

        result = _cli(workspace, monkeypatch, "run", PIPELINE)

        assert result.exit_code == 0, result.output
        assert model.call_count == 4
        assert all(len(shown) == 1 for shown in model.calls)
