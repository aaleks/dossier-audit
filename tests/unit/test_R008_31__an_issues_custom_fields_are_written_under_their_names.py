"""R8.31 — `jira-issue-markdown` writes each custom field a person reads, under its name.

A custom field arrives as `customfield_10050` in an issue's `fields`. The name a
person knows it by is in the payload's `names`, and the kind of value it holds in
its `schema`, when the fetch asked for them (R1.28). A field is written when that
kind is one a person reads; Jira Software's own machinery, declared `any`, and
`Sprint`, which Data Center fills with a Java object's dump, are left out.

`INC-4821` is `tests/fixtures/jira/INC-4821.json`, which was fetched before
R1.28 and so has no `names`. Each test here gives it `names` and `schema` in the
shape Jira Software Data Center 10.3 sends them -- system fields named beside
the custom ones, and a custom field's schema carrying `custom` and `customId` --
and the custom fields `specs/_fixtures.md` records for this rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.domain.jira_issue import note

ISSUE = Path(__file__).resolve().parents[1] / "fixtures" / "jira" / "INC-4821.json"

# What `expand=names,schema` adds for the system fields: named and typed like the
# custom ones, and never written as one.
SYSTEM_NAMES = {
    "summary": "Summary",
    "status": "Status",
    "created": "Created",
    "updated": "Updated",
    "description": "Description",
    "assignee": "Assignee",
    "labels": "Labels",
}
SYSTEM_SCHEMA = {
    "summary": {"type": "string", "system": "summary"},
    "status": {"type": "status", "system": "status"},
    "created": {"type": "datetime", "system": "created"},
    "updated": {"type": "datetime", "system": "updated"},
    "description": {"type": "string", "system": "description"},
    "assignee": {"type": "user", "system": "assignee"},
    "labels": {"type": "array", "items": "string", "system": "labels"},
}

TEXTFIELD = "com.atlassian.jira.plugin.system.customfieldtypes:textarea"
SELECT = "com.atlassian.jira.plugin.system.customfieldtypes:select"
MULTISELECT = "com.atlassian.jira.plugin.system.customfieldtypes:multiselect"
USERPICKER = "com.atlassian.jira.plugin.system.customfieldtypes:userpicker"

ROOT_CAUSE = ("customfield_10050", "Root cause", {"type": "string", "custom": TEXTFIELD})
SEVERITY = ("customfield_10051", "Severity", {"type": "option", "custom": SELECT})
AFFECTED = (
    "customfield_10052",
    "Affected services",
    {"type": "array", "items": "option", "custom": MULTISELECT},
)
COMMANDER = ("customfield_10053", "Incident commander", {"type": "user", "custom": USERPICKER})

# Jira Software's own, as Data Center 10.3 declared them on 2026-09-27.
DEVELOPMENT = (
    "customfield_10000",
    "Development",
    {
        "type": "any",
        "custom": "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummary",
    },
)
RANK = (
    "customfield_10105",
    "Rank",
    {"type": "any", "custom": "com.pyxis.greenhopper.jira:gh-lexo-rank"},
)
SPRINT = (
    "customfield_10104",
    "Sprint",
    {"type": "array", "items": "string", "custom": "com.pyxis.greenhopper.jira:gh-sprint"},
)


def option(value: str, id: str) -> dict:
    """An option as Jira sends one: its value, beside its `self` link and id."""
    return {
        "self": f"https://jira.example.internal/rest/api/2/customFieldOption/{id}",
        "value": value,
        "id": id,
    }


KELLER = {
    "self": "https://jira.example.internal/rest/api/2/user?username=mkeller",
    "name": "mkeller",
    "key": "mkeller",
    "displayName": "m.keller",
    "active": True,
}


def issue(*custom: tuple[tuple[str, str, dict], object], named: bool = True) -> bytes:
    """`INC-4821` holding each `(field, value)` in `custom`.

    With `names` and `schema` when `named`, as a fetch after R1.28 has them.
    `customfield_10042` is R8.16 row 6's value no note may carry, and a payload
    with `names` would name it; it is taken out, so each test here sees only
    the fields its row is about.
    """
    payload = json.loads(ISSUE.read_bytes())
    payload["fields"].pop("customfield_10042")
    for (field, _, _), value in custom:
        payload["fields"][field] = value
    if named:
        payload["names"] = {**SYSTEM_NAMES, **{field: name for (field, name, _), _ in custom}}
        payload["schema"] = {
            **SYSTEM_SCHEMA,
            **{
                field: {**schema, "customId": int(field.removeprefix("customfield_"))}
                for (field, _, schema), _ in custom
            },
        }
    return json.dumps(payload).encode("utf-8")


def unchanged(text: str) -> str:
    return text


def custom_lines(payload: bytes) -> list[str]:
    """The lines between `**Updated:**` and `**Attachments:**`: where custom fields go."""
    written = note(payload, markup=unchanged).split("\n")
    updated = next(n for n, line in enumerate(written) if line.startswith("**Updated:**"))
    attachments = written.index("**Attachments:** report.pdf")
    return written[updated + 1 : attachments]


class TestAnIssuesCustomFieldsAreWrittenUnderTheirNames:
    """R8.31 — a custom field a person reads, under the name Jira gives it."""

    def test_a_text_field_is_written_as_sent_after_the_updated_line(self):
        """Row 1: the one where `Root cause` holds a sentence."""
        payload = issue((ROOT_CAUSE, "Expired certificate on the payment gateway"))

        assert custom_lines(payload) == [
            "**Root cause:** Expired certificate on the payment gateway"
        ]

    def test_an_option_is_written_as_its_value(self):
        """Row 2: the one where `Severity` is `Sev 2`, beside its `self` link and id."""
        payload = issue((SEVERITY, option("Sev 2", "10001")))

        assert custom_lines(payload) == ["**Severity:** Sev 2"]

    def test_an_array_of_options_is_written_as_their_values_joined(self):
        """Row 3: the one where `Affected services` holds two options, in Jira's order."""
        payload = issue(
            (AFFECTED, [option("payments-api", "10020"), option("checkout", "10021")])
        )

        assert custom_lines(payload) == ["**Affected services:** payments-api, checkout"]

    def test_a_user_is_written_as_their_display_name(self):
        """Row 4: the one where `Incident commander` is `m.keller`, whose login is `mkeller`."""
        payload = issue((COMMANDER, KELLER))

        assert custom_lines(payload) == ["**Incident commander:** m.keller"]

    def test_jira_softwares_machinery_is_left_out(self):
        """Counter-example, row 5: the one where `Development` and `Rank` are `any`.

        `Development` held a Java object's string of 3 KB on Data Center 10.3,
        and `Rank` held `0|i0000f:`. Neither is anything a person reads.
        """
        dump = (
            "{summaryBean=com.atlassian.jira.plugin.devstatus.rest.SummaryBean@6b1f1c2a"
            "[cachedValue=...]}"
        )
        payload = issue((DEVELOPMENT, dump), (RANK, "0|i0000f:"))

        written = note(payload, markup=unchanged)

        assert custom_lines(payload) == []
        assert "Development" not in written and "summaryBean" not in written
        assert "Rank" not in written and "0|i0000f:" not in written

    def test_a_sprint_is_left_out(self):
        """Counter-example, row 6: the one where `Sprint` holds a sprint.

        An array of strings, which a person would read, but Data Center fills
        each with a Java object's dump: it is left out by what it is,
        `gh-sprint`, rather than by its type.
        """
        sprint = (
            "com.atlassian.greenhopper.service.sprint.Sprint@3f2a1b"
            "[id=1,rapidViewId=1,state=ACTIVE,name=INC Sprint 1]"
        )
        payload = issue((SPRINT, [sprint]))

        written = note(payload, markup=unchanged)

        assert custom_lines(payload) == []
        assert "Sprint" not in written

    def test_a_field_holding_nothing_has_no_line(self):
        """Counter-example, row 7: the one where `Severity` is `null`."""
        payload = issue((SEVERITY, None))

        assert custom_lines(payload) == []

    def test_a_payload_without_names_has_the_note_it_had(self):
        """Counter-example, row 8: the one held before R1.28, with no `names`.

        The custom fields are in `fields`, and nothing says what they are
        called. No custom field is written, and the note is R8.16's, as it was.
        """
        payload = issue(
            (ROOT_CAUSE, "Expired certificate on the payment gateway"),
            (SEVERITY, option("Sev 2", "10001")),
            named=False,
        )

        assert note(payload, markup=unchanged) == note(issue(named=False), markup=unchanged)
        assert custom_lines(payload) == []

    def test_the_lines_are_ordered_by_name_and_then_by_id(self):
        """The rule's order: by name, and by id where two fields share one.

        Given in neither order, and two fields both called `Severity`.
        """
        other_severity = ("customfield_10049", "Severity", SEVERITY[2])
        payload = issue(
            (SEVERITY, option("Sev 2", "10001")),
            (ROOT_CAUSE, "Expired certificate on the payment gateway"),
            (COMMANDER, KELLER),
            (other_severity, option("Sev 3", "10002")),
            (AFFECTED, [option("payments-api", "10020")]),
        )

        assert custom_lines(payload) == [
            "**Affected services:** payments-api",
            "**Incident commander:** m.keller",
            "**Root cause:** Expired certificate on the payment gateway",
            "**Severity:** Sev 3",
            "**Severity:** Sev 2",
        ]

    @pytest.mark.parametrize(
        ("schema", "value", "written"),
        [
            ({"type": "number"}, 42, "42"),
            ({"type": "date"}, "2026-08-05", "2026-08-05"),
            (
                {"type": "datetime"},
                "2026-08-05T09:12:00.000+0000",
                "2026-08-05T09:12:00.000+0000",
            ),
            (
                {"type": "option-with-child"},
                {"value": "Hardware", "id": "10030", "child": {"value": "Disk", "id": "10031"}},
                "Hardware - Disk",
            ),
            ({"type": "option-with-child"}, {"value": "Hardware", "id": "10030"}, "Hardware"),
            ({"type": "user"}, {"name": "mkeller"}, "mkeller"),
            ({"type": "version"}, {"name": "2.4.0", "id": "10200", "released": True}, "2.4.0"),
            (
                {"type": "array", "items": "user"},
                [KELLER, {"name": "aaleks", "displayName": "a.aleks"}],
                "m.keller, a.aleks",
            ),
            (
                {"type": "array", "items": "version"},
                [{"name": "2.4.0"}, {"name": "2.4.1"}],
                "2.4.0, 2.4.1",
            ),
            (
                {"type": "array", "items": "string"},
                ["checkout", "", "payments"],
                "checkout, payments",
            ),
            ({"type": "array", "items": "option"}, [], ""),
            ({"type": "array", "items": "any"}, ["0|i0000f:"], ""),
            ({"type": "string"}, {"value": "Sev 2"}, ""),
            ({"type": "number"}, True, ""),
        ],
        ids=[
            "number as sent",
            "date as sent",
            "time as sent",
            "option with its child",
            "option with no child",
            "user with no display name",
            "version as its name",
            "array of users",
            "array of versions",
            "array skipping an empty item",
            "empty array",
            "array of any",
            "object where a string was declared",
            "true where a number was declared",
        ],
    )
    def test_each_kind_of_value_is_written_as_the_rule_says(
        self, schema: dict, value: object, written: str
    ):
        """The rule's list of how values are written, beyond the rows' four kinds.

        An empty rendering, as an empty array is, has no line; nor has an array
        of a type no person reads, nor a value that is not what its type says.
        """
        field = ("customfield_10060", "Impact", schema)

        assert custom_lines(issue((field, value))) == (
            [f"**Impact:** {written}"] if written else []
        )
