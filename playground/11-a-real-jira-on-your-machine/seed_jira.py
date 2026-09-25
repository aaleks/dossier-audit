#!/usr/bin/env python3
"""Put incidents into the playground's local Jira, and then disturb them.

Exercise 11 audits a real Jira. Something has to create the issues, and it is
not `dossier`: the connector's whole promise is that every route it has is a
`GET` (R1.1). This script is the other half of that sentence -- the writer, kept
deliberately outside the tool, in the playground where it belongs.

    seed_jira.py wait                 block until Jira answers RUNNING
    seed_jira.py seed                 create the project and four incidents
    seed_jira.py show PLAY-1          print the issue JSON, as dossier will hold it
    seed_jira.py touch PLAY-1         add a label: `updated` moves, the description does not
    seed_jira.py edit PLAY-1          change the description: both move
    seed_jira.py replace-file PLAY-1  new bytes behind the same filename
    seed_jira.py delete PLAY-4        remove the issue entirely

Credentials come from the same two variables `sources.yaml` names, so the `.env`
you write for `dossier` is the one this script reads:

    DOSSIER_JIRA_USER=admin
    DOSSIER_JIRA_TOKEN=<the admin password from the setup wizard>
    DOSSIER_JIRA_URL=http://localhost:8080      (optional; this is the default)

The four incidents are `playground/corpus/incidents/PLAY-100*.md`, the same
notes exercise 01 synced from a folder -- so what changed between that exercise
and this one is where they came from, and one thing that follows from it: an
issue's description is Jira wiki markup, so each note's markdown is written as
wiki markup when it becomes one (`wiki_markup` below).

Jira assigns its own keys. A project keyed `PLAY` numbers its issues `PLAY-1`,
`PLAY-2`, ... and there is no REST route that would let this script ask for
`PLAY-1001` instead. That is worth noticing rather than working around: with a
folder, the document key was a filename you chose; here it is the source's, and
the ledger takes whatever the source says (ground rule 3 is satisfied either
way -- every key here still begins with `PLAY-`).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "incidents"

PROJECT_KEY = "PLAY"
PROJECT_NAME = "Playground Incidents"

# The file every incident carries. Its declared type is sent by this script in
# the multipart part, which is what Jira stores and later reports as `mimeType`
# -- and `mimeType` is what dossier believes over the transport's header and
# over the filename (R2.16, R8.3). So the media type of these attachments is a
# decision made here, visibly, rather than something guessed from ".md".
ATTACHMENT_NAME = "postmortem.md"
ATTACHMENT_TYPE = "text/markdown"

TIMEOUT = httpx.Timeout(60.0)

# The em dash the corpus headings use, written as an escape so this file stays
# ASCII and no editor can helpfully replace it with something else.
EM_DASH = "—"


class SeedFailed(RuntimeError):
    """Jira refused something, with the route and what it said."""


def client(args: argparse.Namespace) -> httpx.Client:
    """An authenticated client, or a message naming the variable that is missing."""
    user = os.environ.get("DOSSIER_JIRA_USER", "")
    token = os.environ.get("DOSSIER_JIRA_TOKEN", "")
    if not user or not token:
        raise SeedFailed(
            "set DOSSIER_JIRA_USER and DOSSIER_JIRA_TOKEN to the administrator "
            "account you created in the setup wizard.\n"
            "  export DOSSIER_JIRA_USER=admin\n"
            "  export DOSSIER_JIRA_TOKEN=<that account's password>"
        )
    pair = base64.b64encode(f"{user}:{token}".encode()).decode("ascii")
    return httpx.Client(
        base_url=args.url.rstrip("/"),
        timeout=TIMEOUT,
        headers={
            "Authorization": f"Basic {pair}",
            "Accept": "application/json",
            # Jira rejects a write from a client it thinks might be a browser
            # being tricked, unless the request opts out of the XSRF check.
            "X-Atlassian-Token": "no-check",
        },
    )


def call(http: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    """One request, or `SeedFailed` naming the route, the status and the body.

    Jira's errors are in the body, not the reason phrase. A 400 that says only
    "Bad Request" sends you looking in the wrong place for ten minutes.
    """
    response = http.request(method, path, **kwargs)
    if not response.is_success:
        detail = response.text.strip()
        raise SeedFailed(f"{method} {path} -> {response.status_code}\n{detail[:800]}")
    return response


# --------------------------------------------------------------------------
# waiting


def wait(args: argparse.Namespace) -> int:
    """Block until Jira answers RUNNING, or say what it is answering instead.

    FIRST_RUN means the port is open and the setup wizard has not been completed.
    That is not something this script can finish for you -- it needs a licence
    key, which needs an Atlassian account.
    """
    deadline = time.monotonic() + args.timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{args.url.rstrip('/')}/status", timeout=10.0)
            state = response.json().get("state", "")
        except (httpx.HTTPError, ValueError):
            state = ""

        if state == "RUNNING":
            print(f"Jira is RUNNING at {args.url}")
            return 0
        if state and state != last:
            print(f"  {state} ...")
            last = state
        time.sleep(5)

    print(
        f"Jira did not reach RUNNING within {args.timeout}s "
        f"(last state: {last or 'no answer'})."
    )
    if last == "FIRST_RUN":
        print("Open the URL above and finish the setup wizard: it needs an evaluation licence.")
    return 1


# --------------------------------------------------------------------------
# seeding

# The markdown the corpus notes use, and nothing more: a `##` heading, `**strong**`,
# and a `- ` list whose items wrap onto indented lines.
HEADING = re.compile(r"^(#{1,6}) (\S.*)$")
STRONG = re.compile(r"\*\*(\S(?:[^*\n]*\S)?)\*\*")
BULLET = "- "
CONTINUATION = "  "


def wiki_markup(markdown: str) -> str:
    """A corpus note's markdown as Jira wiki markup, which is what a description is.

    Jira's REST API version 2 stores a description as wiki markup and returns it
    as such, and `dossier` reads it that way (R8.17). Posting the note's markdown
    as it stands would seed a Jira holding text in a format no Jira description
    has: `**Severity:**` would be read as emphasis wrapped in stars and come back
    `***Severity:***`, and `## Impact` is not a heading in wiki markup at all. So
    each construct the notes use is written as its wiki markup -- `h2. Impact`,
    `*Severity:*`, `* item` -- and a list item's indented continuation joins the
    item, since a wiki-markup list item is one line. Everything else, including
    where a paragraph's lines break, is left as written. Read back through
    `jira2markdown`, as `dossier` reads it, each description is its note again,
    byte for byte, but for those joined lines.

    Written out rather than taken from a library. mistletoe (MIT, pure Python)
    ships a Jira renderer in `mistletoe.contrib`, but it escapes every hyphen --
    `checkout\\-api` -- and runs the three field lines into one paragraph, and the
    playground's tooling installs nothing but httpx.
    """
    lines: list[str] = []
    for line in markdown.splitlines():
        line = STRONG.sub(r"*\1*", line)
        heading = HEADING.match(line)
        if heading:
            lines.append(f"h{len(heading[1])}. {heading[2]}")
        elif line.startswith(BULLET):
            lines.append(f"* {line[len(BULLET) :]}")
        elif line.startswith(CONTINUATION) and lines and lines[-1].startswith("* "):
            lines[-1] = f"{lines[-1]} {line.strip()}"
        else:
            lines.append(line)
    return "\n".join(lines)


def incidents() -> list[tuple[str, str, str]]:
    """Each corpus note as (summary, description, whole note), in key order.

    The first line is `# PLAY-1001 -- Checkout timeouts after ...`; the summary
    is the half after the dash, and the description is everything below it,
    written as wiki markup. The third value is the file as written, heading and
    all -- what gets attached, so that the attachment is the note and not a
    second copy of the description. That difference is deliberate: the issue and
    its file are separate documents (R1.6), and two documents whose text was
    identical would make it impossible to tell which one a span was grounded in.
    """
    found = []
    for path in sorted(CORPUS.glob("PLAY-100*.md")):
        text = path.read_text(encoding="utf-8")
        heading, _, body = text.partition("\n")
        _, _, title = heading.lstrip("# ").partition(EM_DASH)
        found.append(
            (title.strip() or heading.lstrip("# ").strip(), wiki_markup(body.strip()), text)
        )
    if not found:
        raise SeedFailed(f"no incident notes under {CORPUS}")
    return found


def issue_type(http: httpx.Client) -> str:
    """The name of an issue type this project will accept.

    Asked rather than assumed: which types a project has depends on the template
    it was created from, and a hard-coded "Task" is the kind of thing that works
    on the instance it was written against and nowhere else.
    """
    response = http.get("/rest/api/2/issue/createmeta", params={"projectKeys": PROJECT_KEY})
    if response.is_success:
        for project in response.json().get("projects", []):
            names = [t["name"] for t in project.get("issuetypes", []) if not t.get("subtask")]
            for preferred in ("Task", "Bug", "Story"):
                if preferred in names:
                    return preferred
            if names:
                return names[0]
    return "Task"


def ensure_project(http: httpx.Client, *, lead: str) -> None:
    """Create the project, or say nothing if it is already there."""
    existing = http.get(f"/rest/api/2/project/{PROJECT_KEY}")
    if existing.is_success:
        print(f"project {PROJECT_KEY} already exists")
        return

    call(
        http,
        "POST",
        "/rest/api/2/project",
        json={
            "key": PROJECT_KEY,
            "name": PROJECT_NAME,
            "projectTypeKey": "software",
            "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-basic",
            "lead": lead,
            "assigneeType": "PROJECT_LEAD",
        },
    )
    print(f"created project {PROJECT_KEY} ({PROJECT_NAME})")


def attach(http: httpx.Client, key: str, body: str) -> None:
    """Put the note on the issue as a file, with the type this script chooses."""
    call(
        http,
        "POST",
        f"/rest/api/2/issue/{key}/attachments",
        files={"file": (ATTACHMENT_NAME, body.encode("utf-8"), ATTACHMENT_TYPE)},
    )


def seed(args: argparse.Namespace) -> int:
    with client(args) as http:
        ensure_project(http, lead=os.environ["DOSSIER_JIRA_USER"])
        kind = issue_type(http)
        print(f"issue type: {kind}")

        for position, (summary, description, note) in enumerate(incidents()):
            created = call(
                http,
                "POST",
                "/rest/api/2/issue",
                json={
                    "fields": {
                        "project": {"key": PROJECT_KEY},
                        "summary": summary,
                        "description": description,
                        "issuetype": {"name": kind},
                    }
                },
            ).json()
            key = created["key"]
            # Only the first incident carries a file. One is enough to show that
            # an issue and its attachment are two addresses with two ledger rows
            # (R1.6); four would be three more documents saying the same thing,
            # and three more rules to write into the stub's reply file.
            if position == 0:
                attach(http, key, note)
                print(f"created {key}  {summary}  + {ATTACHMENT_NAME}")
            else:
                print(f"created {key}  {summary}")

    print("\nSeeded: four issues, one of them carrying a file. That is five")
    print(f"documents -- {PROJECT_KEY}-1 .. {PROJECT_KEY}-4 and")
    print(f"`{PROJECT_KEY}-1/{ATTACHMENT_NAME}`, which is its own address (R1.6).")
    return 0


# --------------------------------------------------------------------------
# disturbing


def show(args: argparse.Namespace) -> int:
    """The issue JSON, formatted. What dossier holds is this, unformatted (R1.2)."""
    with client(args) as http:
        payload = call(http, "GET", f"/rest/api/2/issue/{args.key}").json()
    fields = payload.get("fields", {})
    print(
        json.dumps(
            {
                "key": payload.get("key"),
                "fields": {
                    "summary": fields.get("summary"),
                    "updated": fields.get("updated"),
                    "labels": fields.get("labels"),
                    "status": (fields.get("status") or {}).get("name"),
                    "attachment": [
                        {
                            "id": a.get("id"),
                            "filename": a.get("filename"),
                            "mimeType": a.get("mimeType"),
                            "content": a.get("content"),
                        }
                        for a in fields.get("attachment") or []
                    ],
                },
            },
            indent=2,
        )
    )
    print(
        "\n`updated` is the version marker dossier compares (R1.5); each attachment\n"
        "`id` is that file's own marker, and `content` is the URL a fetch follows."
    )
    return 0


def touch(args: argparse.Namespace) -> int:
    """Add a label: `updated` moves, and the summary and description do not.

    This is the pair of facts task 5 is about. The version marker moving is what
    makes sync re-fetch the issue (R2.1). The label and `updated` both sit under
    `fields`, which `fields: [key, fields]` projects whole, so the content hash
    moves too and a new snapshot is written for an issue nobody edited (R2.10).
    """
    with client(args) as http:
        call(
            http,
            "PUT",
            f"/rest/api/2/issue/{args.key}",
            json={"update": {"labels": [{"add": f"touched-{int(time.time())}"}]}},
        )
    print(f"{args.key}: label added. `updated` has moved; summary and description have not.")
    return 0


def edit(args: argparse.Namespace) -> int:
    """Change the description: the version marker and the projection both move."""
    addition = "\n\n" + wiki_markup(
        "## Correction\n\nFinance restated the recorded loss after reconciliation."
    )
    with client(args) as http:
        current = call(http, "GET", f"/rest/api/2/issue/{args.key}").json()
        description = (current.get("fields", {}).get("description") or "").rstrip()
        if addition.strip() in description:
            print(f"{args.key}: already corrected")
            return 0
        call(
            http,
            "PUT",
            f"/rest/api/2/issue/{args.key}",
            json={"fields": {"description": description + addition}},
        )
    print(f"{args.key}: description changed. The next sync repoints this row (R2.18).")
    return 0


def replace_file(args: argparse.Namespace) -> int:
    """New bytes behind the same filename, which Jira gives a new attachment id.

    Jira has no "replace"; it has delete and add. The filename is reused, so the
    document key is unchanged -- and the id, which is the file's version marker,
    is not. That is the pair R2.6 turns on.
    """
    with client(args) as http:
        issue = call(http, "GET", f"/rest/api/2/issue/{args.key}").json()
        attachments = issue.get("fields", {}).get("attachment") or []
        body = ""
        for existing in attachments:
            if existing.get("filename") == ATTACHMENT_NAME:
                body = call(http, "GET", existing["content"]).text
                call(http, "DELETE", f"/rest/api/2/attachment/{existing['id']}")
                print(f"{args.key}: removed attachment id {existing['id']}")
        if not body:
            raise SeedFailed(f"{args.key} carries no {ATTACHMENT_NAME} to replace")
        attach(http, args.key, body.rstrip() + "\n\n<!-- revised -->\n")
    print(f"{args.key}: {ATTACHMENT_NAME} re-uploaded with a new id and new bytes.")
    return 0


def delete(args: argparse.Namespace) -> int:
    """Remove the issue. Nothing tells dossier; that is the point of task 6."""
    with client(args) as http:
        call(http, "DELETE", f"/rest/api/2/issue/{args.key}", params={"deleteSubtasks": "true"})
    print(
        f"{args.key}: deleted.\n"
        "A windowed listing cannot show you this -- it omits every unchanged issue\n"
        "too, so there is nothing to subtract from (R1.11). `dossier sync --full`\n"
        "asks for the whole source and tombstones it (R2.22)."
    )
    return 0


# --------------------------------------------------------------------------

COMMANDS = {
    "wait": wait,
    "seed": seed,
    "show": show,
    "touch": touch,
    "edit": edit,
    "replace-file": replace_file,
    "delete": delete,
}

NEEDS_KEY = {"show", "touch", "edit", "replace-file", "delete"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument(
        "key", nargs="?", help="the issue to act on, for the commands that take one"
    )
    parser.add_argument(
        "--url", default=os.environ.get("DOSSIER_JIRA_URL", "http://localhost:8080")
    )
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds `wait` will wait")
    args = parser.parse_args(argv)

    if args.command in NEEDS_KEY and not args.key:
        parser.error(f"`{args.command}` needs an issue key, for example {PROJECT_KEY}-1")

    try:
        return COMMANDS[args.command](args)
    except SeedFailed as failure:
        print(f"error: {failure}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
