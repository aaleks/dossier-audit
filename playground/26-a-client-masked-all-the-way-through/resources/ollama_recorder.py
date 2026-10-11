#!/usr/bin/env python3
"""Stand in front of Ollama, pass every request through, and log what it was asked to embed.

    python ollama_recorder.py --port 11435 --log embed-calls.jsonl

Then point `dossier` at it, in the shell or in `.env`:

    DOSSIER_OLLAMA_URL=http://127.0.0.1:11435

Exercise 25 read what a chat model was sent from the stub's log. An embedding
model has no stub here: a vector is only worth what the real model meant
(exercise 20). So this sits between `dossier` and the real Ollama instead. It
forwards each request unchanged to `--ollama` (http://127.0.0.1:11434 unless
given), returns Ollama's answer unchanged, and appends one JSON line per
`/api/embed` request to the log: the model, and every text it was asked to
embed, verbatim. The vectors are not logged.

Standard library only. It listens on 127.0.0.1 and talks to nothing but the
Ollama it is given.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Recorder(BaseHTTPRequestHandler):
    ollama = "http://127.0.0.1:11434"
    log_path: Path | None = None

    def do_GET(self) -> None:  # noqa: N802 -- the name http.server calls
        self._forward(None)

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.startswith("/api/embed") and self.log_path is not None:
            asked = json.loads(body or b"{}")
            texts = asked.get("input", [])
            line = {
                "at": datetime.now(UTC).isoformat(),
                "model": asked.get("model"),
                "input": [texts] if isinstance(texts, str) else texts,
            }
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._forward(body)

    def _forward(self, body: bytes | None) -> None:
        request = urllib.request.Request(
            self.ollama + self.path,
            data=body,
            method=self.command,
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as answer:
                status, payload, kind = answer.status, answer.read(), answer.headers
        except urllib.error.HTTPError as refused:
            status, payload, kind = refused.code, refused.read(), refused.headers
        self.send_response(status)
        self.send_header("Content-Type", kind.get("Content-Type", "application/json"))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args(argv)
    Recorder.ollama = args.ollama.rstrip("/")
    Recorder.log_path = args.log
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Recorder)
    print(
        f"recording Ollama on http://127.0.0.1:{args.port} -> {Recorder.ollama}"
        f" · log {args.log}",
        flush=True,
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
