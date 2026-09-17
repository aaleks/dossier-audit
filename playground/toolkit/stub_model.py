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
`reply` is either a string, returned verbatim as the model's answer, or an object,
returned as compact JSON. A request matching no rule gets `default`, or a 422 if
there is none -- silence would look like a model bug rather than a missing rule.

Every request is appended to the log as one JSON line, so an exercise can ask how
many calls a command made, which is the claim several rules are about (R5.5,
R7.18, R11.2).
"""

from __future__ import annotations

import argparse
import json
import sys
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

    def reply_to(self, prompt: str) -> str | None:
        default: object | None = None
        for path in self._paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            for rule in document.get("rules", []):
                if all(needle in prompt for needle in rule.get("match", [])):
                    return _as_text(rule["reply"])
            if default is None:
                default = document.get("default")
        return None if default is None else _as_text(default)


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

        prompt = "\n".join(
            str(message.get("content", "")) for message in body.get("messages", [])
        )
        reply = self.replies.reply_to(prompt)
        self._record(body, prompt, reply)

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

    def _record(self, body: dict, prompt: str, reply: str | None) -> None:
        """One JSON line per call: what was asked, and whether a rule answered it."""
        if self.log_path is None:
            return
        line = {
            "at": datetime.now(UTC).isoformat(),
            "model": body.get("model"),
            "schema": bool(body.get("response_format")),
            "prompt_chars": len(prompt),
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
