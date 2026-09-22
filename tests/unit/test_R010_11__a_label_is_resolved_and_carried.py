"""R010.11 — the label a command is given is rendered into its name and tagged.

The acceptance test beside this one proves a command carries the label a person
typed. This one proves the three decisions underneath: which of the flag and the
variable wins, what `{label}` renders, and when the tag exists at all.

Pure -- the flag arrives as an argument and the environment as a mapping, so
every one of them is provable with a dict.
"""

from __future__ import annotations

from dossier.domain.tracking import SEPARATOR, label_for, run_name, tags

RUN_ID = "20260806T142203Z-4f1a"


class TestALabelIsResolvedAndCarried:
    """R10.11 — the label a command is given is rendered into its name and tagged."""

    def test_the_flag_wins_over_the_variable(self):
        """Example 2: the one where a shell sets a label and the command names another.

        An argument wins over a default everywhere else in this tool, and a
        variable is a default. A variable that could not be overridden per
        command would let `DOSSIER_MLFLOW_RUN_LABEL=nightly` in a shell silently
        relabel a run someone made by hand.
        """
        assert label_for("v2", {"DOSSIER_MLFLOW_RUN_LABEL": "nightly"}) == "v2"

    def test_a_label_set_only_in_the_environment_is_used(self):
        """Example 3: the one where a scheduled job labels everything it runs."""
        assert label_for(None, {"DOSSIER_MLFLOW_RUN_LABEL": "nightly"}) == "nightly"

    def test_no_label_anywhere_is_no_label(self):
        """Counter-example (row 4): the one where nobody labelled it.

        An empty string rather than `None`, because what renders and what is
        tagged both read it, and two callers each handling a `None` is two
        chances to handle it differently.
        """
        assert label_for(None, {}) == ""

    def test_a_label_renders_with_its_own_separator(self):
        """Example 1, the name half: the one where the label closes the name.

        The separator belongs to `{label}`, as it belongs to `{prefix}` (R10.10).
        A template carrying its own ` · ` would leave a trailing one on every
        unlabelled record.
        """
        assert (
            run_name(kind="run", values={"run_id": RUN_ID, "label": "v2"}, environ={})
            == f"{RUN_ID}{SEPARATOR}v2"
        )

    def test_an_unlabelled_name_ends_where_its_last_value_does(self):
        """Counter-example (row 4), the name half: the one with nothing to append."""
        name = run_name(kind="run", values={"run_id": RUN_ID, "label": ""}, environ={})

        assert name == RUN_ID
        assert not name.endswith(SEPARATOR)

    def test_a_labelled_record_is_tagged_with_it(self):
        """Example 1, the tag half: the one a person filters a list of runs by."""
        assert tags(kind="run", pipeline="incident-audit", label="v2") == {
            "dossier.kind": "run",
            "dossier.pipeline": "incident-audit",
            "dossier.label": "v2",
        }

    def test_an_unlabelled_record_carries_no_label_tag_at_all(self):
        """Counter-example (row 4), the tag half: absent, not present and empty.

        A label is supplied or it is not, so absent reads correctly as "nobody
        labelled it". `dossier.regressed` goes the other way (R11.9 row 3): the
        command computes it for every comparison, so there an absent tag would
        read as a record written before the rule existed.
        """
        assert "dossier.label" not in tags(kind="run", pipeline="incident-audit")
