# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pillow>=10",
#   "numpy>=1.26",
#   "pyyaml>=6",
#   "kokoro-onnx==0.6.1",
#   "soundfile>=0.12",
#   "imageio-ffmpeg>=0.5",
#   "pypdfium2>=4.30",
# ]
# ///
"""Turn a deck into a narrated video: each slide shown while its speaker notes are spoken.

    uv run playground/tutorial/architecture/narrate.py             # the .pptx -> .mp4
    uv run playground/tutorial/architecture/narrate.py --stills    # the slides as PNGs
    uv run playground/tutorial/architecture/narrate.py --no-voice  # silent, for timing

The slides are drawn by PowerPoint where it is installed, and by LibreOffice
otherwise. The notes are spoken by Kokoro, as the quickstart's narration is
(`../render.py`, whose voice, cache and subtitle writing this reuses), and the
deck's sections become the video's chapters. Edit the deck in PowerPoint, or
`deck.js` and build it again, and run this to make the video match.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from render import FPS, RATE, Voice, clock, sentences, srt_time  # noqa: E402

VOICE, SPEED = "af_heart", 1.0
LEAD_IN, BETWEEN_SENTENCES, AFTER_SLIDE = 0.8, 0.3, 1.1

# What the voice says for a word the notes spell as it is written. Captions and
# notes keep the written form.
PRONOUNCE = {
    "MLflow": "M L flow",
    "TDD": "T D D",
    "CLI": "C L I",
    "pipeline.yaml": "pipeline dot yammel",
    "YAML": "yammel",
    ".env": "dot E N V",
    "OpenWebUI": "open web U I",
    "OpenAI-compatible": "OpenAI compatible",
    "gpt-5.4-mini": "G P T five point four mini",
    "vLLM": "v L L M",
    "pgvector": "P G vector",
    "nDCG": "N D C G",
    "OCR": "O C R",
    "CID": "C I D",
    "gc": "G C",
    "eval": "e-val",
    "Eval": "E-val",
    "pydantic": "pie dantic",
}

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
}


# --------------------------------------------------------------------------- the deck


def rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """A part's relationships, id -> target path inside the package."""
    folder, name = part.rsplit("/", 1)
    xml = ElementTree.fromstring(z.read(f"{folder}/_rels/{name}.rels"))
    out = {}
    for rel in xml.findall("rel:Relationship", NS):
        target = rel.get("Target")
        path = target.lstrip("/") if target.startswith("/") else f"{folder}/{target}"
        parts: list[str] = []
        for piece in path.split("/"):
            if piece == "..":
                parts.pop()
            elif piece != ".":
                parts.append(piece)
        out[rel.get("Id")] = "/".join(parts)
    return out


def read_deck(path: Path) -> tuple[str, list[tuple[str, str]]]:
    """The deck's title, and each slide's (section, notes) in order."""
    with zipfile.ZipFile(path) as z:
        presentation = ElementTree.fromstring(z.read("ppt/presentation.xml"))
        targets = rels(z, "ppt/presentation.xml")
        order = [
            (sid.get("id"), targets[sid.get(f"{{{NS['r']}}}id")])
            for sid in presentation.find("p:sldIdLst", NS)
        ]
        section_of: dict[str, str] = {}
        for section in presentation.iter(f"{{{NS['p14']}}}section"):
            for sid in section.iter(f"{{{NS['p14']}}}sldId"):
                section_of[sid.get("id")] = section.get("name")
        try:
            core = ElementTree.fromstring(z.read("docProps/core.xml"))
            titles = [e.text for e in core if e.tag.endswith("}title") and e.text]
            title = titles[0] if titles else path.stem
        except KeyError:
            title = path.stem
        slides = []
        for sid, part in order:
            notes = ""
            for target in rels(z, part).values():
                if "/notesSlides/" in target:
                    notes = notes_text(ElementTree.fromstring(z.read(target)))
            slides.append((section_of.get(sid, ""), notes))
    return title, slides


def notes_text(xml: ElementTree.Element) -> str:
    """The text of a notes page's body placeholder, its paragraphs joined."""
    for shape in xml.iter(f"{{{NS['p']}}}sp"):
        ph = shape.find(".//p:nvPr/p:ph", NS)
        if ph is not None and ph.get("type") == "body":
            paragraphs = [
                "".join(t.text or "" for t in p.iter(f"{{{NS['a']}}}t"))
                for p in shape.iter(f"{{{NS['a']}}}p")
            ]
            return " ".join(p.strip() for p in paragraphs if p.strip())
    return ""


# --------------------------------------------------------------------------- the slides


def export_slides(deck: Path, out: Path) -> list[Path]:
    """Each slide as a 1920 x 1080 PNG, drawn by PowerPoint or LibreOffice."""
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("slide-*.png"):
        old.unlink()
    if sys.platform == "win32" and powerpoint_installed():
        script = f"""
$ErrorActionPreference = 'Stop'
$pp = New-Object -ComObject PowerPoint.Application
try {{
  $p = $pp.Presentations.Open('{deck}', -1, 0, 0)
  $i = 0
  foreach ($s in $p.Slides) {{
    $i++
    $s.Export((Join-Path '{out}' ('slide-{{0:D3}}.png' -f $i)), 'PNG', 1920, 1080)
  }}
  $p.Close()
}} finally {{ $pp.Quit() }}
"""
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    else:
        office = shutil.which("soffice") or shutil.which("libreoffice")
        if not office:
            raise SystemExit("neither PowerPoint nor LibreOffice is here to draw the slides")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [office, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(deck)],
                check=True,
            )
            import pypdfium2

            pdf = pypdfium2.PdfDocument(Path(tmp) / f"{deck.stem}.pdf")
            for i, page in enumerate(pdf, start=1):
                image = page.render(scale=1920 / page.get_width()).to_pil()
                image.resize((1920, 1080)).save(out / f"slide-{i:03}.png")
    return sorted(out.glob("slide-*.png"))


def powerpoint_installed() -> bool:
    key = "Registry::HKEY_CLASSES_ROOT\\PowerPoint.Application"
    probe = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"[bool](Get-ItemProperty '{key}' -ErrorAction SilentlyContinue)"],
        capture_output=True, text=True,
    )  # fmt: skip
    return probe.stdout.strip() == "True"


# --------------------------------------------------------------------------- the video


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("deck", nargs="?", type=Path, default=HERE / "architecture.pptx")
    parser.add_argument("--stills", action="store_true", help="the slides as PNGs, and stop")
    parser.add_argument("--no-voice", action="store_true", help="silence, timed by word count")
    arguments = parser.parse_args(argv)
    deck = arguments.deck.resolve()
    if not deck.is_file():
        raise SystemExit(f"no deck at {deck}: run `node deck.js` in {HERE} first")

    title, slides = read_deck(deck)
    silent = [i for i, (_, notes) in enumerate(slides, start=1) if not notes]
    if silent:
        raise SystemExit(f"slides with no notes to speak: {', '.join(map(str, silent))}")

    if arguments.stills:
        images = export_slides(deck, deck.with_name(f"{deck.stem}-slides"))
        print(f"{len(images)} slides in {images[0].parent}")
        return 0

    voice = Voice(VOICE, SPEED, PRONOUNCE, arguments.no_voice)
    clips: list[tuple[float, np.ndarray]] = []
    subtitles: list[tuple[float, float, str]] = []
    shown: list[tuple[float, float]] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    for section, notes in slides:
        start = t
        if section and (not chapters or chapters[-1][1] != section):
            chapters.append((start, section))
        t += LEAD_IN
        for sentence in sentences(notes):
            clip = voice.say(sentence)
            duration = len(clip) / RATE
            clips.append((t, clip))
            subtitles.append((t, t + duration, sentence))
            t += duration + BETWEEN_SENTENCES
        t += AFTER_SLIDE
        shown.append((start, t))
    end = t
    print(f"{clock(end)} long · {len(slides)} slides · {len(chapters)} chapters", flush=True)

    out = deck.with_suffix(".mp4")
    work = Path(tempfile.mkdtemp(prefix="narrate-"))
    try:
        images = export_slides(deck, work)
        if len(images) != len(slides):
            raise SystemExit(f"{len(images)} slides drawn, {len(slides)} in the deck")
        concat = ["ffconcat version 1.0"]
        for image, (a, b) in zip(images, shown, strict=True):
            frames = round(b * FPS) - round(a * FPS)
            concat += [f"file '{image.name}'", f"duration {frames / FPS:.6f}"]
        concat.append(f"file '{images[-1].name}'")
        (work / "frames.txt").write_text("\n".join(concat) + "\n", encoding="utf-8")

        total = np.zeros(int(round(end * FPS) / FPS * RATE), dtype=np.float32)
        for at, clip in clips:
            i = int(at * RATE)
            total[i : i + len(clip)] += clip[: len(total) - i]
        total *= 0.89 / (float(np.max(np.abs(total))) or 1.0)
        import soundfile

        soundfile.write(work / "narration.wav", total, RATE, subtype="PCM_16")

        srt = out.with_suffix(".srt")
        srt.write_text(
            "\n".join(
                f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n"
                for i, (a, b, text) in enumerate(subtitles, start=1)
            ),
            encoding="utf-8",
            newline="\n",
        )
        meta = [";FFMETADATA1", f"title={title}"]
        for (a, name), (b, _) in zip(chapters, chapters[1:] + [(end, "")], strict=True):
            meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(a * 1000)}"]
            meta += [f"END={int(b * 1000)}", f"title={name}"]
        chapters_txt = work / "chapters.txt"
        chapters_txt.write_text("\n".join(meta) + "\n", encoding="utf-8", newline="\n")

        import imageio_ffmpeg

        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(work / "frames.txt"),
            "-i", str(work / "narration.wav"),
            "-i", str(work / "chapters.txt"),
            "-i", str(srt),
            "-map", "0:v", "-map", "1:a", "-map", "3:s",
            "-map_metadata", "2", "-map_chapters", "2",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "128k",
            "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
            # The concat list names the last slide twice, or its duration is
            # dropped; the second one would then play for as long again.
            "-t", f"{end:.3f}",
            "-movflags", "+faststart", str(out),
        ]  # fmt: skip
        subprocess.run(command, check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"{out.name} · {clock(end)} · {out.stat().st_size / 1e6:.1f} MB")
    print("chapters:")
    for at, name in chapters:
        print(f"  {clock(at)}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
