#!/usr/bin/env python3
"""A stub model server for the playground: an endpoint, never a provider.

`dossier` reaches a model over one OpenAI-compatible route, `POST
<url>/chat/completions` (R9.12). Nothing in `dossier` cares what is behind it, so
a few hundred lines of the standard library are enough to stand in for one -- and
that is what makes the exercises here runnable offline, in seconds, at zero cost,
with the same code path a real endpoint takes.

This is the playground's counterpart to `FakeModelClient` in `tests/`: it answers
from a rule file and it counts calls. It is not part of `dossier`, nothing under
`src/` or `tests/` imports it, and it never becomes a provider -- a provider is a
package that declares a `dossier.models` entry point (R9.1, R9.7).

    python playground/toolkit/stub_model.py --replies replies.json --port 8099

Then, in the workspace:

    DOSSIER_OPENAI_URL=http://127.0.0.1:8099/api

A reply file is a list of rules, first match wins:

    {
      "rules": [
        {
          "comment": "the retry: put the more specific rule first",
          "match": ["PLAY-1003", "<validation_error>"],
          "reply": {"document": "PLAY-1003", "fields": []}
        },
        {"match": ["PLAY-1003"], "reply": "not json at all"}
      ],
      "default": {"document": "unknown", "fields": []}
    }

`match` is a list of substrings that must all appear in the rendered prompt.
A rule may also carry `"image": "<sha256 prefix>"`, which matches the bytes of a
picture the request carried -- the only thing that differs between two calls of a
`per_part` step, whose prompt is the same template on every page (R3.12).
`reply` is either a string, returned verbatim as the model's answer, or an object,
returned as compact JSON. A request matching no rule gets `default`, or a 422 if
there is none -- silence would look like a model bug rather than a missing rule.

Every request is appended to the log as one JSON line, so an exercise can ask how
many calls a command made, which is the claim several rules are about (R5.5,
R7.18, R11.2).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Replies:
    """The rules this server answers from, reloaded on every request.

    Reloaded rather than held, so editing a file is visible on the next call
    without restarting the server. A playground exercise edits one several times.

    Several files may be given. They are consulted in the order they were passed
    and the first matching rule wins, so a file of overrides goes first and a base
    file of ordinary answers goes last -- which is how one exercise changes one
    document's answer without restating the other three.
    """

    def __init__(self, paths: list[Path]) -> None:
        self._paths = paths

    def reply_to(self, prompt: str, images: Sequence[str] = ()) -> str | None:
        default: object | None = None
        for path in self._paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            for rule in document.get("rules", []):
                if _matches(rule, prompt=prompt, images=images):
                    return _as_text(rule["reply"])
            if default is None:
                default = document.get("default")
        return None if default is None else _as_text(default)


def _matches(rule: dict, *, prompt: str, images: Sequence[str]) -> bool:
    """Whether this rule answers this request.

    `match` is the text half: every substring must appear in the rendered
    prompt. `image` is the picture half, and it exists because a `per_part` step
    gives a stub nothing else to go on -- the prompt is the same template for
    page one and page four, and what differs between the two calls is the
    picture. That is not a quirk of this server: it is exactly what the stage
    key says, which holds the part's content hash and nothing else about it
    (R3.12).

    So a rule names a page by the sha256 of its bytes, as short a prefix as is
    unambiguous. `make_observability_docs.py --digests` prints them, rendered by
    the shipped converters, which is where the numbers in a reply file come from.
    """
    if not all(needle in prompt for needle in rule.get("match", [])):
        return False
    wanted = rule.get("image")
    if wanted is None:
        return True
    return any(digest.startswith(wanted.lower()) for digest in images)


def _asked(messages: Sequence[dict]) -> tuple[str, list[str]]:
    """The text of a request, and the sha256 of every picture it carried.

    A message's `content` is a plain string when a stage has only text, and a
    list of parts when it has pictures beside it: `{"type": "text"}` first, then
    one `{"type": "image_url"}` per page, each a `data:` URI (R9.16). Both forms
    are read here, and the text is joined so a rule's `match` sees the same
    prompt whichever shape it arrived in.

    `str(content)` would "work" on the list form and is the trap: the prompt
    would then be a Python repr with a megabyte of base64 inside it, every
    `prompt_chars` in the log would be nonsense, and a `match` would silently
    start matching against base64.
    """
    text: list[str] = []
    images: list[str] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            text.append(content)
            continue
        for part in content:
            if part.get("type") == "text":
                text.append(part.get("text", ""))
            elif part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                _, _, encoded = url.partition(",")
                images.append(hashlib.sha256(base64.b64decode(encoded)).hexdigest())
    return "\n".join(text), images


def _as_text(reply: object) -> str:
    """A rule's reply as the model would have returned it.

    A string goes back verbatim -- that is how a rule serves a malformed answer on
    purpose (R6.2). An object is serialised compactly, which is what a model
    answering under a JSON schema returns.
    """
    if isinstance(reply, str):
        return reply
    return json.dumps(reply, sort_keys=True, separators=(",", ":"))


class Handler(BaseHTTPRequestHandler):
    """One POST per completion, and a `GET /models` for the providers that ask."""

    replies: Replies
    log_path: Path | None
    served_model: str = "stub"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server requires
        """`GET <url>/models`, which `hf` reads before its first completion (R9.6)."""
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"data": [{"id": self.served_model, "root": self.served_model}]})
            return
        self._json(404, {"error": f"no route {self.path}"})

    def do_POST(self) -> None:  # noqa: N802 - the name http.server requires
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": f"no route {self.path}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError as error:
            self._json(400, {"error": f"the request body is not JSON: {error}"})
            return

        prompt, images = _asked(body.get("messages", []))
        reply = self.replies.reply_to(prompt, images)
        self._record(body, prompt, reply, images)

        if reply is None:
            # Named, not answered. A stub that invented something here would send
            # a plausible answer into a stage and turn a missing rule into a
            # puzzle about grounding.
            self._json(
                422,
                {"error": "no rule matched this prompt, and the file declares no default"},
            )
            return

        self._json(200, {"choices": [{"message": {"role": "assistant", "content": reply}}]})

    def _record(
        self, body: dict, prompt: str, reply: str | None, images: Sequence[str]
    ) -> None:
        """One JSON line per call: what was asked, and whether a rule answered it."""
        if self.log_path is None:
            return
        line = {
            "at": datetime.now(UTC).isoformat(),
            "model": body.get("model"),
            "schema": bool(body.get("response_format")),
            "prompt_chars": len(prompt),
            # How many pictures this call carried, and which. Counted here
            # because "the pages reached the model" is not something the text of
            # a prompt can show: a per_part step's prompt is the same on every
            # page, and the picture is the whole of the difference (R3.12,
            # R9.16). A log with nothing but `prompt_chars` would read as four
            # identical calls.
            "images": len(images),
            "image_sha256": [digest[:16] for digest in images],
            "matched": reply is not None,
            # The first line of the prompt is enough to tell a stage call from a
            # judge call by eye, and keeps a log readable in a terminal.
            "prompt_first_line": prompt.strip().splitlines()[0] if prompt.strip() else "",
        }
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(line, sort_keys=True) + "\n")

    def _json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        """Quiet by default: the call log is the record, and stderr is the exercise's."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--replies",
        required=True,
        type=Path,
        action="append",
        help="a rule file; repeat it to layer overrides in front of a base file",
    )
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="append one JSON line per call to this file",
    )
    parser.add_argument(
        "--served-model",
        default="stub",
        help="what GET /models reports, for a provider that checks (R9.6)",
    )
    arguments = parser.parse_args(argv)

    missing = [path for path in arguments.replies if not path.is_file()]
    if missing:
        print(f"no reply file at {', '.join(str(path) for path in missing)}", file=sys.stderr)
        return 2

    Handler.replies = Replies(arguments.replies)
    Handler.log_path = arguments.log
    Handler.served_model = arguments.served_model

    server = ThreadingHTTPServer((arguments.host, arguments.port), Handler)
    print(
        f"stub model on http://{arguments.host}:{arguments.port} "
        f"· rules {', '.join(str(path) for path in arguments.replies)} "
        f"· log {arguments.log or 'off'}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
