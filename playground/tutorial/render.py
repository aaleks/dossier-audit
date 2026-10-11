# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pillow>=10",
#   "numpy>=1.26",
#   "pyyaml>=6",
#   "kokoro-onnx==0.6.1",
#   "soundfile>=0.12",
#   "imageio-ffmpeg>=0.5",
# ]
# ///
"""Turn a recorded tutorial into a narrated video.

    uv run playground/tutorial/render.py                 # quickstart.yaml -> quickstart.mp4
    uv run playground/tutorial/render.py --no-voice      # silent, for checking the layout
    uv run playground/tutorial/render.py --still 95      # one frame, at 95 s, as a PNG

Reads the lesson and the recording `record.py` made of it, speaks the narration
with Kokoro, an open text-to-speech model that runs on this machine, types each
command a character at a time, shows the output the command printed when it was
recorded, and writes an MP4 with chapters and subtitles, an `.srt` beside it.

Its dependencies are declared above, so `uv run` installs them apart from
dossier's own. Kokoro's model, about 350 MB, is downloaded once into
`~/.cache/kokoro-onnx/` and checked against its SHA-256. Nothing here is part of
dossier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
WORK = HERE.parent / "work"

W, H, FPS = 1920, 1080, 30
RATE = 24_000  # Kokoro's sample rate

KOKORO = {
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{}"
CACHE = Path.home() / ".cache"

# Colours: a dark editor theme, so text reads at a glance on any screen.
BG = (15, 18, 27)
TEXT, MUTED, DIM = (192, 202, 245), (120, 130, 170), (70, 78, 110)
ACCENT, GREEN, AMBER, RED = (122, 162, 247), (158, 206, 106), (224, 175, 104), (247, 118, 142)
TERM_BG, TERM_BAR, HIGHLIGHT = (26, 27, 38), (19, 20, 29), (40, 52, 88)
WHITE = (236, 239, 250)

TERM_BOX = (80, 104, 1840, 884)
TERM_BAR_H = 46
MONO_SIZE = 22
CAPTION_BOX = (120, 900, 1800, 1066)

TYPE_CPS = 26  # an AI types quickly, and still legibly


# --------------------------------------------------------------------------- fonts

FONT_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
]
FONTS = {
    "mono": [
        "JetBrainsMono-Regular.ttf",
        "CascadiaMono.ttf",
        "consola.ttf",
        "DejaVuSansMono.ttf",
        "Menlo.ttc",
    ],
    "sans": ["Inter-Regular.ttf", "segoeui.ttf", "DejaVuSans.ttf", "Helvetica.ttc"],
    "bold": [
        "Inter-SemiBold.ttf",
        "seguisb.ttf",
        "segoeuib.ttf",
        "DejaVuSans-Bold.ttf",
        "Helvetica.ttc",
    ],
}


def find_font(kind: str) -> str:
    for name in FONTS[kind]:
        for directory in FONT_DIRS:
            if not directory.is_dir():
                continue
            direct = directory / name
            if direct.is_file():
                return str(direct)
            found = next(directory.rglob(name), None) if directory.name == "fonts" else None
            if found:
                return str(found)
    raise SystemExit(f"no {kind} font found; looked for {', '.join(FONTS[kind])}")


_fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(find_font(kind), size)
    return _fonts[key]


def mono_metrics() -> tuple[float, int, int, int]:
    f = font("mono", MONO_SIZE)
    char_w = f.getlength("M")
    line_h = round(MONO_SIZE * 1.36)
    x0, y0, x1, y1 = TERM_BOX
    cols = int((x1 - x0 - 56) // char_w)
    rows = int((y1 - y0 - TERM_BAR_H - 34) // line_h)
    return char_w, line_h, cols, rows


# --------------------------------------------------------------------------- states

Segment = tuple[str, tuple[int, int, int]]


@dataclass(frozen=True)
class Visual:
    kind: str  # "title", "card", "slide" or "term"
    chapter: int = -1
    heading: str = ""
    subtitle: str = ""
    bullets: tuple[str, ...] = ()
    shown: int = 0
    lines: tuple[tuple[Segment, ...], ...] = ()
    lit: frozenset[int] = frozenset()
    typing: bool = False
    cursor: bool = True


@dataclass(frozen=True)
class Frame:
    visual: Visual
    caption: str | None
    chapters: tuple[str, ...]


@dataclass
class Timeline:
    visual: list[tuple[float, Visual]] = field(default_factory=list)
    captions: list[tuple[float, str | None]] = field(default_factory=list)
    clips: list[tuple[float, np.ndarray]] = field(default_factory=list)
    chapters: list[tuple[float, str]] = field(default_factory=list)
    subtitles: list[tuple[float, float, str]] = field(default_factory=list)
    end: float = 0.0

    def show(self, t: float, visual: Visual) -> None:
        self.visual.append((t, visual))
        self.end = max(self.end, t)


# --------------------------------------------------------------------------- voice


class Voice:
    """Kokoro, sentence by sentence, cached by what was said and how."""

    def __init__(self, name: str, speed: float, pronounce: dict[str, str], silent: bool):
        self.name, self.speed, self.silent = name, speed, silent
        self.rules = [
            (re.compile(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])"), v)
            for k, v in sorted(pronounce.items(), key=lambda kv: -len(kv[0]))
        ]
        self.cache = CACHE / "dossier-tutorial" / "tts"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.kokoro = None

    def spoken(self, text: str) -> str:
        for pattern, replacement in self.rules:
            text = pattern.sub(replacement, text)
        return text

    def say(self, sentence: str) -> np.ndarray:
        if self.silent:
            return np.zeros(int(RATE * max(1.2, len(sentence.split()) / 2.7)), dtype=np.float32)
        spoken = self.spoken(sentence)
        key = hashlib.sha256(f"{self.name}|{self.speed}|{spoken}".encode()).hexdigest()
        path = self.cache / f"{key}.npy"
        if path.is_file():
            return np.load(path)
        if self.kokoro is None:
            from kokoro_onnx import Kokoro

            model_dir = kokoro_files()
            self.kokoro = Kokoro(
                str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin")
            )
        samples, rate = self.kokoro.create(
            spoken, voice=self.name, speed=self.speed, lang="en-us"
        )
        assert rate == RATE, rate
        samples = trim(np.asarray(samples, dtype=np.float32))
        np.save(path, samples)
        return samples


def kokoro_files() -> Path:
    directory = CACHE / "kokoro-onnx"
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in KOKORO.items():
        path = directory / name
        if not path.is_file() or sha256(path) != digest:
            print(f"downloading {name} ...", flush=True)
            partial = path.with_suffix(".part")
            urllib.request.urlretrieve(KOKORO_URL.format(name), partial)
            if sha256(partial) != digest:
                partial.unlink()
                raise SystemExit(f"{name}: SHA-256 does not match the pinned one")
            partial.replace(path)
    return directory


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def trim(samples: np.ndarray, floor: float = 0.004) -> np.ndarray:
    loud = np.flatnonzero(np.abs(samples) > floor)
    if loud.size == 0:
        return samples
    pad = int(RATE * 0.04)
    return samples[max(0, loud[0] - pad) : loud[-1] + pad]


def sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Za-z0-9\"'])", text)
    return [p for p in parts if p]


# --------------------------------------------------------------------------- terminal


def colour_of(line: str) -> tuple[int, int, int]:
    stripped = line.strip()
    if stripped.startswith("!") or "<- weakest" in line:
        return AMBER
    if (
        "<- regression" in line
        or stripped.startswith("[exit")
        or "error" in stripped.lower()[:12]
    ):
        return RED
    if stripped.startswith("#"):
        return MUTED
    if re.search(r"overall 100\.0%|0 failed$", line):
        return GREEN
    return TEXT


def prompt_line(prompt: str, typed: str) -> tuple[Segment, ...]:
    path, _, mark = prompt.rstrip().rpartition(" ")
    return ((path + " ", ACCENT), (mark + " ", GREEN), (typed, WHITE))


def wrap(lines: tuple[tuple[Segment, ...], ...], cols: int, lit: frozenset[int]):
    """Each logical line as the rows it fills, with whether it is lit.

    A row breaks after its last space or slash, as a terminal user would read
    it, unless that would leave the row less than two thirds full.
    """
    rows = []
    for index, segments in enumerate(lines):
        chars = [(ch, colour) for text, colour in segments for ch in text]
        while len(chars) > cols:
            cut = cols
            for i in range(cols - 1, int(cols * 2 / 3), -1):
                if chars[i][0] in " /":
                    cut = i + 1
                    break
            rows.append((regroup(chars[:cut]), index in lit))
            chars = chars[cut:]
        rows.append((regroup(chars), index in lit))
    return rows


def regroup(chars: list[tuple[str, tuple[int, int, int]]]) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    for ch, colour in chars:
        if segments and segments[-1][1] == colour:
            segments[-1] = (segments[-1][0] + ch, colour)
        else:
            segments.append((ch, colour))
    return tuple(segments)


# --------------------------------------------------------------------------- drawing

_backgrounds: dict[str, Image.Image] = {}


def background() -> Image.Image:
    # Flat: a gradient this dark is quantised by H.264 into a visible step.
    if "bg" not in _backgrounds:
        _backgrounds["bg"] = Image.new("RGB", (W, H), BG)
    return _backgrounds["bg"].copy()


def draw_header(d: ImageDraw.ImageDraw, frame: Frame, title: str) -> None:
    d.text((80, 34), "dossier", font=font("bold", 30), fill=ACCENT)
    x = 80 + font("bold", 30).getlength("dossier")
    d.text((x, 34), f"  ·  {title}", font=font("sans", 30), fill=MUTED)
    chapter = frame.visual.chapter
    if 0 <= chapter < len(frame.chapters):
        label = f"{chapter + 1} / {len(frame.chapters)}   {frame.chapters[chapter]}"
        f = font("sans", 28)
        d.text((W - 80 - f.getlength(label), 36), label, font=f, fill=TEXT)
        # one dot per chapter, the current one lit, under the label
        n = len(frame.chapters)
        x0 = W - 80 - (n - 1) * 22
        for i in range(n):
            colour = ACCENT if i == chapter else (DIM if i > chapter else MUTED)
            r = 5 if i == chapter else 4
            d.ellipse((x0 + i * 22 - r, 88 - r, x0 + i * 22 + r, 88 + r), fill=colour)


def draw_caption(d: ImageDraw.ImageDraw, caption: str | None) -> None:
    if not caption:
        return
    f = font("sans", 38)
    x0, y0, x1, y1 = CAPTION_BOX
    words, lines, current = caption.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if f.getlength(trial) > (x1 - x0 - 60) and current:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    line_h = 50
    total = line_h * len(lines)
    top = y0 + (y1 - y0 - total) // 2
    widest = max(f.getlength(line) for line in lines)
    pad_x, pad_y = 28, 12
    d.rounded_rectangle(
        (
            W / 2 - widest / 2 - pad_x,
            top - pad_y,
            W / 2 + widest / 2 + pad_x,
            top + total + pad_y - 6,
        ),
        radius=14,
        fill=(8, 10, 16),
    )
    for i, line in enumerate(lines):
        d.text((W / 2 - f.getlength(line) / 2, top + i * line_h), line, font=f, fill=WHITE)


def draw_terminal(d: ImageDraw.ImageDraw, v: Visual, workspace_title: str) -> None:
    x0, y0, x1, y1 = TERM_BOX
    d.rounded_rectangle(
        (x0 + 6, y0 + 10, x1 + 6, y1 + 12), radius=16, fill=(6, 8, 12)
    )  # shadow
    d.rounded_rectangle((x0, y0, x1, y1), radius=16, fill=TERM_BG)
    d.rounded_rectangle((x0, y0, x1, y0 + TERM_BAR_H), radius=16, fill=TERM_BAR)
    d.rectangle((x0, y0 + TERM_BAR_H - 16, x1, y0 + TERM_BAR_H), fill=TERM_BAR)
    for i, colour in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cx, cy = x0 + 26 + i * 24, y0 + TERM_BAR_H // 2
        d.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=colour)
    f = font("sans", 22)
    d.text(
        ((x0 + x1) / 2 - f.getlength(workspace_title) / 2, y0 + 10),
        workspace_title,
        font=f,
        fill=MUTED,
    )
    if v.typing:
        badge = "AI is typing"
        bw = f.getlength(badge) + 44
        bx = x1 - 20 - bw
        d.rounded_rectangle(
            (bx, y0 + 9, bx + bw, y0 + TERM_BAR_H - 9), radius=12, fill=(35, 45, 75)
        )
        d.ellipse((bx + 12, y0 + 19, bx + 22, y0 + 29), fill=GREEN)
        d.text((bx + 30, y0 + 10), badge, font=f, fill=TEXT)

    char_w, line_h, cols, rows = mono_metrics()
    mono = font("mono", MONO_SIZE)
    wrapped = wrap(v.lines, cols, v.lit)[-rows:]
    tx, ty = x0 + 28, y0 + TERM_BAR_H + 18
    for r, (segments, lit) in enumerate(wrapped):
        y = ty + r * line_h
        if lit:
            d.rectangle((x0 + 12, y - 3, x1 - 12, y + line_h - 5), fill=HIGHLIGHT)
            d.rectangle((x0 + 12, y - 3, x0 + 16, y + line_h - 5), fill=ACCENT)
        x = tx
        for text, colour in segments:
            d.text((x, y), text, font=mono, fill=colour)
            x += char_w * len(text)
    if v.cursor and wrapped:
        segments, _ = wrapped[-1]
        width = sum(len(t) for t, _ in segments)
        cx = tx + char_w * width
        cy = ty + (len(wrapped) - 1) * line_h
        d.rectangle((cx + 1, cy + 2, cx + char_w - 1, cy + line_h - 6), fill=TEXT)


def draw_slide(d: ImageDraw.ImageDraw, v: Visual) -> None:
    d.rounded_rectangle((80, 104, 1840, 884), radius=16, fill=(22, 26, 40))
    f = font("bold", 66)
    d.text((170, 190), v.heading, font=f, fill=WHITE)
    d.rectangle((172, 290, 172 + 120, 296), fill=ACCENT)
    fb = font("sans", 42)
    for i, bullet in enumerate(v.bullets[: v.shown]):
        y = 350 + i * 82
        d.ellipse((176, y + 20, 192, y + 36), fill=ACCENT)
        d.text((220, y), bullet, font=fb, fill=TEXT)


def draw_card(d: ImageDraw.ImageDraw, v: Visual) -> None:
    if v.kind == "title":
        f, fs = font("bold", 96), font("sans", 44)
        d.text((W / 2 - f.getlength(v.heading) / 2, 360), v.heading, font=f, fill=WHITE)
        d.rectangle((W / 2 - 80, 500, W / 2 + 80, 507), fill=ACCENT)
        d.text((W / 2 - fs.getlength(v.subtitle) / 2, 550), v.subtitle, font=fs, fill=MUTED)
        return
    label = f"Chapter {v.chapter + 1}"
    fl, ft = font("sans", 40), font("bold", 84)
    d.text((W / 2 - fl.getlength(label) / 2, 400), label, font=fl, fill=ACCENT)
    d.text((W / 2 - ft.getlength(v.heading) / 2, 466), v.heading, font=ft, fill=WHITE)


def draw(frame: Frame, title: str, workspace_title: str) -> Image.Image:
    image = background()
    d = ImageDraw.Draw(image)
    v = frame.visual
    if v.kind in ("title", "card"):
        draw_card(d, v)
    else:
        draw_header(d, frame, title)
        if v.kind == "slide":
            draw_slide(d, v)
        else:
            draw_terminal(d, v, workspace_title)
    draw_caption(d, frame.caption)
    return image


def draw_to(job: tuple[Frame, str, str, str]) -> None:
    frame, title, workspace_title, path = job
    draw(frame, title, workspace_title).save(path, compress_level=1)


# --------------------------------------------------------------------------- directing


class Director:
    def __init__(self, lesson: dict, recording: dict, voice: Voice):
        self.lesson, self.voice = lesson, voice
        self.prompt = recording["prompt"]
        self.recorded = {(c["chapter"], c["scene"]): c for c in recording["commands"]}
        self.timeline = Timeline()
        self.random = random.Random(20261011)
        self.lines: list[tuple[Segment, ...]] = []
        self.chapter = -1

    # narration -------------------------------------------------------------
    def speak(self, t: float, text: str | None) -> float:
        if not text:
            return t
        for sentence in sentences(text):
            clip = self.voice.say(sentence)
            duration = len(clip) / RATE
            self.timeline.clips.append((t, clip))
            self.timeline.captions.append((t, sentence))
            self.timeline.subtitles.append((t, t + duration, sentence))
            t += duration + 0.3
        self.timeline.captions.append((t - 0.1, None))
        return t

    # pictures ---------------------------------------------------------------
    def term(
        self,
        t: float,
        typed: str | None = None,
        typing: bool = False,
        lit=frozenset(),
        cursor=True,
    ):
        lines = list(self.lines)
        if typed is not None:
            lines.append(prompt_line(self.prompt, typed))
        self.timeline.show(
            t,
            Visual(
                "term",
                self.chapter,
                lines=tuple(lines),
                lit=frozenset(lit),
                typing=typing,
                cursor=cursor,
            ),
        )

    def direct(self) -> Timeline:
        t = 0.0
        self.timeline.show(
            t, Visual("title", heading=self.lesson["title"], subtitle=self.lesson["subtitle"])
        )
        t += 3.5
        for c, chapter in enumerate(self.lesson["chapters"]):
            self.chapter = c
            self.timeline.chapters.append((t, chapter["title"]))
            if c > 0:
                self.timeline.show(t, Visual("card", c, heading=chapter["title"]))
                t += 2.2
            self.lines = []
            for s, scene in enumerate(chapter["scenes"]):
                if "slide" in scene:
                    t = self.slide(t, scene)
                elif "run" in scene:
                    t = self.run(t, scene, self.recorded[(c, s)])
                else:
                    self.term(t, typed="")
                    t = self.speak(t + 0.2, scene.get("say")) + 0.4
        self.timeline.end = t + 2.0
        return self.timeline

    def slide(self, t: float, scene: dict) -> float:
        slide = scene["slide"]
        bullets = tuple(slide.get("bullets", []))
        start = t
        end = self.speak(t + 0.6, scene.get("say"))
        span = max(end - start - 1.5, 0.5)
        for i in range(len(bullets) + 1):
            when = start + (0 if i == 0 else 0.6 + span * (i - 1) / max(len(bullets), 1))
            self.timeline.show(
                when,
                Visual(
                    "slide", self.chapter, heading=slide["heading"], bullets=bullets, shown=i
                ),
            )
        return end + 1.0

    def run(self, t: float, scene: dict, recorded: dict) -> float:
        command = recorded["command"]
        self.term(t, typed="")
        speech_end = self.speak(t + 0.3, scene.get("say"))
        clock = t + 0.9
        for i in range(1, len(command) + 1):
            self.term(clock, typed=command[:i], typing=True)
            delay = self.random.uniform(0.55, 1.45) / TYPE_CPS
            if command[i - 1] == " " and self.random.random() < 0.25:
                delay += 0.12
            clock += delay
        self.term(clock, typed=command, typing=False)
        clock += 0.45
        # Enter: the command line stays, its output follows, a new prompt waits.
        self.lines.append(prompt_line(self.prompt, command))
        self.term(clock, cursor=False)
        clock += min(0.2 + recorded["seconds"] * 0.5, 1.2)
        first_output = len(self.lines)
        output = recorded["output"].split("\n") if recorded["output"] else []
        if recorded["exit"]:
            output.append(f"[exit {recorded['exit']}]")
        for line in output:
            self.lines.append(((line, colour_of(line)),))
            self.term(clock, cursor=False)
            clock += 0.035
        self.term(clock, typed="")
        then_start = max(clock + 0.5, speech_end + 0.2)
        if not scene.get("then"):
            return then_start + 0.4
        patterns = [re.compile(re.escape(p)) for p in scene.get("highlight", [])]
        lit = {
            i
            for i in range(first_output, len(self.lines))
            if any(p.search("".join(text for text, _ in self.lines[i])) for p in patterns)
        }
        self.term(then_start, typed="", lit=lit)
        then_end = self.speak(then_start, scene["then"])
        self.term(then_end + 0.2, typed="")
        return then_end + 0.6


def blink(timeline: Timeline) -> list[tuple[float, Visual]]:
    """A waiting prompt's cursor blinks, as a real one does."""
    events = sorted(timeline.visual, key=lambda e: e[0])
    out: list[tuple[float, Visual]] = []
    for (t, v), (t_next, _) in zip(events, events[1:] + [(timeline.end, None)], strict=True):
        out.append((t, v))
        if v.kind == "term" and v.cursor and not v.typing and t_next - t > 1.2:
            on, when = False, t + 0.55
            while when < t_next - 0.3:
                out.append((when, Visual(**{**v.__dict__, "cursor": on})))
                on, when = not on, when + 0.55
    return out


def frames_of(timeline: Timeline, chapters: tuple[str, ...]) -> list[tuple[int, Frame]]:
    """(first video frame, what it shows), one entry per change."""
    visual = blink(timeline)
    captions = sorted(timeline.captions, key=lambda e: e[0])
    times = sorted({round(t * FPS) for t, _ in visual} | {round(t * FPS) for t, _ in captions})
    vi = ci = 0
    current_v, current_c = visual[0][1], None
    out: list[tuple[int, Frame]] = []
    for f in times:
        while vi < len(visual) and round(visual[vi][0] * FPS) <= f:
            current_v = visual[vi][1]
            vi += 1
        while ci < len(captions) and round(captions[ci][0] * FPS) <= f:
            current_c = captions[ci][1]
            ci += 1
        frame = Frame(current_v, current_c, chapters)
        if out and out[-1][1] == frame:
            continue
        if out and out[-1][0] == f:
            out[-1] = (f, frame)
        else:
            out.append((f, frame))
    return out


# --------------------------------------------------------------------------- output


def write_audio(timeline: Timeline, path: Path) -> None:
    total = np.zeros(int(round(timeline.end * FPS) / FPS * RATE), dtype=np.float32)
    for t, clip in timeline.clips:
        start = int(t * RATE)
        total[start : start + len(clip)] += clip[: len(total) - start]
    peak = float(np.max(np.abs(total))) or 1.0
    total *= 0.89 / peak
    import soundfile

    soundfile.write(path, total, RATE, subtype="PCM_16")


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3_600_000:02}:{ms // 60_000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_srt(timeline: Timeline, path: Path) -> None:
    blocks = [
        f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n"
        for i, (a, b, text) in enumerate(sorted(timeline.subtitles), start=1)
    ]
    path.write_text("\n".join(blocks), encoding="utf-8", newline="\n")


def write_chapters(timeline: Timeline, title: str, path: Path) -> list[tuple[float, str]]:
    marks = timeline.chapters
    lines = [";FFMETADATA1", f"title={title}"]
    for (start, name), (end, _) in zip(marks, marks[1:] + [(timeline.end, "")], strict=True):
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start * 1000)}",
            f"END={int(end * 1000)}",
            f"title={name}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return marks


def clock(t: float) -> str:
    return f"{int(t) // 60}:{int(t) % 60:02}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lesson", nargs="?", type=Path, default=HERE / "quickstart.yaml")
    parser.add_argument("--no-voice", action="store_true", help="silence, timed by word count")
    parser.add_argument(
        "--still", type=float, help="write the frame at this second as a PNG, and stop"
    )
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 2))
    arguments = parser.parse_args(argv)

    lesson = yaml.safe_load(arguments.lesson.read_text(encoding="utf-8"))
    name = lesson["setup"]["workspace"]
    recording_path = WORK / f"{name}.recording.json"
    if not recording_path.is_file():
        raise SystemExit(f"no recording at {recording_path}: run record.py first")
    recording = json.loads(recording_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(HERE))
    from record import lesson_digest

    if recording["lesson"] != lesson_digest(lesson):
        raise SystemExit(
            "the lesson's commands changed since it was recorded: run record.py again"
        )

    voice = Voice(
        lesson["voice"],
        float(lesson.get("speed", 1.0)),
        lesson.get("pronounce", {}),
        arguments.no_voice,
    )
    timeline = Director(lesson, recording, voice).direct()
    chapters = tuple(ch["title"] for ch in lesson["chapters"])
    frames = frames_of(timeline, chapters)
    title, workspace_title = (
        lesson.get("header", lesson["title"]),
        recording["prompt"].rstrip(" $"),
    )
    print(f"{clock(timeline.end)} long · {len(frames)} distinct frames", flush=True)

    out = arguments.lesson.with_suffix(".mp4")
    if arguments.still is not None:
        target = round(arguments.still * FPS)
        frame = [fr for f, fr in frames if f <= target][-1]
        still = out.with_name(f"{out.stem}-{arguments.still:g}s.png")
        draw(frame, title, workspace_title).save(still)
        print(still)
        return 0

    work = Path(tempfile.mkdtemp(prefix="tutorial-", dir=WORK))
    try:
        jobs = [
            (fr, title, workspace_title, str(work / f"{i:05}.png"))
            for i, (_, fr) in enumerate(frames)
        ]
        with ProcessPoolExecutor(max_workers=arguments.workers) as pool:
            for done, _ in enumerate(pool.map(draw_to, jobs, chunksize=16), start=1):
                if done % 500 == 0:
                    print(f"  {done}/{len(jobs)} frames", flush=True)
        end_frame = round(timeline.end * FPS)
        concat = ["ffconcat version 1.0"]
        for i, (f, _) in enumerate(frames):
            nxt = frames[i + 1][0] if i + 1 < len(frames) else end_frame
            concat += [f"file '{i:05}.png'", f"duration {(nxt - f) / FPS:.6f}"]
        concat.append(f"file '{len(frames) - 1:05}.png'")
        (work / "frames.txt").write_text("\n".join(concat) + "\n", encoding="utf-8")
        write_audio(timeline, work / "narration.wav")
        srt = out.with_suffix(".srt")
        write_srt(timeline, srt)
        marks = write_chapters(timeline, lesson["title"], work / "chapters.txt")

        import imageio_ffmpeg

        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(work / "frames.txt"),
            "-i", str(work / "narration.wav"),
            "-i", str(work / "chapters.txt"),
            "-i", str(srt),
            "-map", "0:v", "-map", "1:a", "-map", "3:s",
            "-map_metadata", "2", "-map_chapters", "2",
            "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "128k",
            "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
            "-movflags", "+faststart", str(out),
        ]  # fmt: skip
        subprocess.run(command, check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    size = out.stat().st_size / 1e6
    print(f"{out.name} · {clock(timeline.end)} · {size:.1f} MB")
    print("chapters:")
    for start, chapter in marks:
        print(f"  {clock(start)}  {chapter}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
