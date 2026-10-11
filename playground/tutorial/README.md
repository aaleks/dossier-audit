# Quickstart video · dossier in ten minutes

A narrated screencast of the core loop, for watching before you type: a
folder of four incident notes taken through `sync`, `convert`, `run --plan`,
`run` and `eval`, then a prompt edit and the regression it causes, caught by
`eval --compare`. An AI types every command live. A voice explains what each
command is for while it types, and what the output says once it appears. Every
output on screen is what the command printed when the video was recorded.

It runs on the playground's stub model, as exercises 01 to 10 do, so you can
follow along offline, at zero cost, and get the same answers. The pipeline
names `openai:gpt-5.4-mini`, and the last chapter says what to change to ask
the real one.

## Watch it

`quickstart.mp4` in this folder, once rendered (see below; the video is
generated, and is not kept in git). About ten minutes, 1080p, with chapters
and English subtitles built in, and an `.srt` beside it.

| # | Chapter | Starts |
|---|---|---|
| 1 | Welcome | 0:00 |
| 2 | The workspace | 0:50 |
| 3 | Where the model is served | 1:38 |
| 4 | Sync and snapshots | 2:08 |
| 5 | A pipeline | 2:56 |
| 6 | Convert, plan and run | 3:49 |
| 7 | The cache | 4:55 |
| 8 | Scoring against gold | 5:25 |
| 9 | A prompt change, and a regression | 5:58 |
| 10 | Status, and where next | 7:14 |

`TRANSCRIPT.md` is the same lesson as text: the narration, and every command
with the output it printed. It is the page to keep open while you type along.

## Type along

From the repository root. Terminal 1, the stub model:

```bash
mkdir -p playground/work/quickstart
.venv/bin/python playground/toolkit/stub_model.py \
    --replies playground/05-a-gold-set-and-dossier-eval/resources/replies-prompt-v2.json \
    --replies playground/05-a-gold-set-and-dossier-eval/resources/replies.json \
    --port 8199 --log playground/work/quickstart/model-calls.jsonl --usage
```

The first reply file only answers once the prompt has the sentence chapter 9
adds, so one stub serves the whole video.

Terminal 2, the workspace the video starts from:

```bash
W=playground/work/quickstart
mkdir -p $W/inbox/incidents $W/gold/incidents
cp -r playground/tutorial/workspace/. $W/
cp playground/corpus/incidents/PLAY-100[1-4].md $W/inbox/incidents/
cp playground/05-a-gold-set-and-dossier-eval/resources/verified-answers/*.json $W/gold/incidents/
printf 'DOSSIER_OPENAI_URL=http://127.0.0.1:8199/api\nDOSSIER_OPENAI_API_KEY=stub\n' > $W/.env
cd $W
export PATH="$PWD/../../../.venv/bin:$PATH"     # .venv/Scripts on Windows
```

Copying the gold files is you accepting them as verified: `dossier` never
writes a gold file itself (R7.7). Then type the commands in `TRANSCRIPT.md`, in
order. Run ids and timestamps will be yours; everything else should match.

## Make the video again

```bash
.venv/bin/python playground/tutorial/record.py     # runs every command, for real
uv run playground/tutorial/render.py               # speaks, types, and writes the MP4
```

`record.py` builds the workspace above in `playground/work/quickstart/`,
starts the stub, runs each command of `quickstart.yaml` in `bash`, and keeps
what it printed in `playground/work/quickstart.recording.json`. It also
writes `TRANSCRIPT.md`. It needs nothing beyond dossier's own install.

`render.py` declares its own dependencies, so `uv run` installs them apart
from dossier's: Pillow draws the frames, ffmpeg (from `imageio-ffmpeg`)
encodes them, and [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), an
open text-to-speech model under Apache-2.0, speaks the narration on this
machine. Its model, about 350 MB, is downloaded once into
`~/.cache/kokoro-onnx/` and checked against a pinned SHA-256. No text is sent
anywhere. A render takes a few minutes. Spoken sentences are cached, so
rendering again after a layout change is quicker.

```bash
uv run playground/tutorial/render.py --no-voice      # silent, timed by word count
uv run playground/tutorial/render.py --still 95      # one frame, at 95 s, as a PNG
```

`render.py` refuses a recording made from different commands, so a lesson whose
commands changed is recorded again before it is rendered.

## Changing the lesson

`quickstart.yaml` is the whole video as data. A chapter is a list of scenes:

| key | what it does |
|---|---|
| `slide:` | a heading and bullets, revealed as the narration goes |
| `run:` | a command, typed live; its output is the recorded one. `{run:first}` and `{run:last}` stand for run ids |
| `say:` | spoken while the command is typed, or over the slide |
| `then:` | spoken once the output is on screen |
| `highlight:` | output lines containing any of these are lit while `then:` is spoken |

Each sentence is one caption, so keep them short. `pronounce:` changes what
the voice reads and never the caption: `gpt-5.4-mini` is read as "G P T five
point four mini". `voice:` is any Kokoro voice, such as `af_heart`,
`am_michael` or `bf_emma`.

> Like the rest of `playground/`, this is practice material. It is not part of
> `dossier`, and nothing under `src/`, `tests/` or `specs/` refers to it.
