#!/usr/bin/env python3
"""Run a tutorial's commands for real, and keep what each one printed.

    .venv/bin/python playground/tutorial/record.py              # quickstart.yaml
    .venv/bin/python playground/tutorial/record.py other.yaml

Builds a fresh workspace under `playground/work/<workspace>/`, starts the
playground's stub model behind it, and runs every `run:` of the lesson in order,
in `bash`, with this interpreter's `dossier` first on PATH. What each command
printed, its exit code and how long it took go to
`playground/work/<workspace>.recording.json`, which `render.py` reads, and the
lesson as text, narration and output together, goes to `TRANSCRIPT.md` beside
the lesson.

Standard library and PyYAML only, both of which dossier's own install already
has, so it runs from the repository's venv. Nothing here is part of dossier.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PLAYGROUND = HERE.parent
WORK = PLAYGROUND / "work"
SHOWN_AS = "~/{workspace}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lesson", nargs="?", type=Path, default=HERE / "quickstart.yaml")
    parser.add_argument(
        "--transcript",
        action="store_true",
        help="rewrite TRANSCRIPT.md from the last recording, after a narration edit",
    )
    arguments = parser.parse_args(argv)

    lesson = yaml.safe_load(arguments.lesson.read_text(encoding="utf-8"))
    setup = lesson["setup"]
    workspace = WORK / setup["workspace"]
    shown_as = SHOWN_AS.format(workspace=setup["workspace"])
    out = WORK / f"{setup['workspace']}.recording.json"
    transcript = arguments.lesson.with_name("TRANSCRIPT.md")
    if arguments.transcript:
        recorded = json.loads(out.read_text(encoding="utf-8"))
        if recorded["lesson"] != lesson_digest(lesson):
            raise SystemExit(
                "the lesson's commands changed since it was recorded: record it again"
            )
        write_transcript(transcript, lesson, recorded["commands"], shown_as)
        return 0
    build_workspace(workspace, setup)

    stub = start_stub(workspace, setup)
    try:
        commands = record(lesson, workspace, shown_as)
    finally:
        stub.terminate()
        stub.wait(timeout=10)

    failed = [c for c in commands if c["exit"] != 0 and not c.get("expect_failure")]
    out.write_text(
        json.dumps(
            {"lesson": lesson_digest(lesson), "prompt": f"{shown_as} $ ", "commands": commands},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"recorded {len(commands)} command(s) -> {shown(out)}")
    write_transcript(transcript, lesson, commands, shown_as)
    for command in failed:
        print(f"! exit {command['exit']}: {command['command']}", file=sys.stderr)
    return 1 if failed else 0


def shown(path: Path) -> str:
    """A path as it reads from the repository root, when it is under it."""
    try:
        return str(path.resolve().relative_to(PLAYGROUND.parent))
    except ValueError:
        return str(path)


def lesson_digest(lesson: dict) -> str:
    """What the recording was made from: every command, in order."""
    runs = [scene.get("run") for chapter in lesson["chapters"] for scene in chapter["scenes"]]
    payload = json.dumps([lesson["setup"], runs], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_workspace(workspace: Path, setup: dict) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    for entry in setup.get("copy", []):
        sources = sorted(glob.glob(str(PLAYGROUND / entry["from"])))
        if not sources:
            raise SystemExit(f"setup: nothing matches {entry['from']}")
        target = workspace / entry["to"]
        target.mkdir(parents=True, exist_ok=True)
        for source in map(Path, sources):
            if source.is_dir():
                shutil.copytree(source, target / source.name, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target / source.name)
    env = setup.get("env")
    if env:
        (workspace / ".env").write_text(
            env.format(port=setup["port"]), encoding="utf-8", newline="\n"
        )


def start_stub(workspace: Path, setup: dict) -> subprocess.Popen:
    stub = setup["stub"]
    command = [
        sys.executable,
        str(PLAYGROUND / "toolkit" / "stub_model.py"),
        "--port",
        str(setup["port"]),
    ]
    for replies in stub["replies"]:
        command += ["--replies", str(PLAYGROUND / replies)]
    if stub.get("log"):
        command += ["--log", str(workspace / stub["log"])]
    if stub.get("usage"):
        command.append("--usage")
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", setup["port"]), timeout=0.5):
                return process
        except OSError:
            if process.poll() is not None:
                raise SystemExit(
                    f"the stub model exited at once: is port {setup['port']} taken?"
                ) from None
            time.sleep(0.2)
    process.terminate()
    raise SystemExit(f"the stub model never answered on port {setup['port']}")


def find_bash() -> str:
    if os.environ.get("DOSSIER_TUTORIAL_BASH"):
        return os.environ["DOSSIER_TUTORIAL_BASH"]
    if os.name == "nt":
        # `bash` on a Windows PATH is often WSL's, which cannot see this venv.
        roots = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        ]
        for root in roots:
            candidate = root / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)
    found = shutil.which("bash")
    if not found:
        raise SystemExit("no bash found; set DOSSIER_TUTORIAL_BASH")
    return found


def command_env(bash: str) -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(Path(sys.executable).parent)]
    if os.name == "nt":
        # Git's own tools (find, sort, head, wc) ahead of System32's namesakes.
        paths.append(str(Path(bash).parent.parent / "usr" / "bin"))
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    env.update(
        {
            "COLUMNS": "100",
            "LINES": "40",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "LC_ALL": "C.UTF-8",
        }
    )
    return env


def resolve(command: str, workspace: Path) -> str:
    runs_dir = workspace / "runs"
    runs = sorted(p.name for p in runs_dir.iterdir() if p.is_dir()) if runs_dir.is_dir() else []

    def run_id(match: re.Match[str]) -> str:
        if not runs:
            raise SystemExit(f"{command}: no run yet for {match.group(0)}")
        return runs[0] if match.group(1) == "first" else runs[-1]

    return re.sub(r"\{run:(first|last)\}", run_id, command)


def sanitise(text: str, workspace: Path, shown_as: str) -> str:
    """The workspace as a viewer's would be named, and nothing of this machine."""
    text = text.replace("\r\n", "\n")
    native = str(workspace)
    forms = {native, native.replace("\\", "/"), workspace.as_posix()}
    if os.name == "nt" and re.match(r"^[A-Za-z]:", native):
        forms.add("/" + native[0].lower() + native[2:].replace("\\", "/"))
    for form in sorted(forms, key=len, reverse=True):
        pattern = re.escape(form) + r"([\\/][^\s'\"]*)?"
        text = re.sub(
            pattern,
            lambda m: shown_as + (m.group(1) or "").replace("\\", "/"),
            text,
            flags=re.IGNORECASE,
        )
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")


def record(lesson: dict, workspace: Path, shown_as: str) -> list[dict]:
    bash = find_bash()
    env = command_env(bash)
    commands = []
    for c, chapter in enumerate(lesson["chapters"]):
        for s, scene in enumerate(chapter["scenes"]):
            if "run" not in scene:
                continue
            command = resolve(scene["run"], workspace)
            started = time.monotonic()
            completed = subprocess.run(
                [bash, "-c", command],
                cwd=workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=600,
            )
            seconds = round(time.monotonic() - started, 2)
            output = sanitise(completed.stdout.decode("utf-8", "replace"), workspace, shown_as)
            commands.append(
                {
                    "chapter": c,
                    "scene": s,
                    "command": command,
                    "output": output,
                    "exit": completed.returncode,
                    "seconds": seconds,
                    "expect_failure": bool(scene.get("expect_failure")),
                }
            )
            print(f"[{completed.returncode}] {command}  ({seconds} s)")
    return commands


def write_transcript(path: Path, lesson: dict, commands: list[dict], shown_as: str) -> None:
    text = render_transcript(lesson, commands, shown_as)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"transcript -> {shown(path)}")


def render_transcript(lesson: dict, commands: list[dict], shown_as: str) -> str:
    by_scene = {(c["chapter"], c["scene"]): c for c in commands}
    lines = [
        f"# {lesson['title']}",
        "",
        f"*{lesson['subtitle']}*",
        "",
        "The narration of the video, and every command it types with the output it",
        "printed when it was recorded. Generated by `record.py` from",
        "`quickstart.yaml`; edit those, not this file.",
        "",
    ]
    for c, chapter in enumerate(lesson["chapters"], start=0):
        lines += [f"## {c + 1} · {chapter['title']}", ""]
        for s, scene in enumerate(chapter["scenes"]):
            if "slide" in scene:
                slide = scene["slide"]
                lines += [f"**{slide['heading']}**", ""]
                lines += [f"- {bullet}" for bullet in slide.get("bullets", [])] + [""]
            if scene.get("say"):
                lines += [f"> {scene['say'].strip()}", ""]
            if (c, s) in by_scene:
                recorded = by_scene[(c, s)]
                block = [f"{shown_as} $ {recorded['command']}"]
                if recorded["output"]:
                    block.append(recorded["output"])
                if recorded["exit"]:
                    block.append(f"[exit {recorded['exit']}]")
                lines += ["```console", *block, "```", ""]
            if scene.get("then"):
                lines += [f"> {scene['then'].strip()}", ""]
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
