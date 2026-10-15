# dossier, from the inside · the second video, and its deck

A narrated tour of how `dossier` is built, what it does today and what could
come next, as a PowerPoint deck and as a video made from it. Where the
quickstart (`../`) shows the commands, this one shows the design behind them:
the two loops it is written in, the two boundaries that keep it reproducible,
a document's way from a source to a search, and the pilot that comes next.

The deck is the source. Each slide's speaker notes are what the voice says
over it, and the deck's sections are the video's chapters, so the two cannot
disagree: change the deck, run the narration again, and the video follows.

## Watch it, or present it

`architecture.mp4` and `architecture.pptx` in this folder, once built (see
below; both are generated, and are not kept in git). The video is about
fourteen minutes, 1080p, with chapters and English subtitles built in, and an
`.srt` beside it. The deck has 25 slides in four sections; its speaker notes
are a script to present it live.

| # | Chapter | Starts |
|---|---|---|
| 1 | Welcome | 0:00 |
| 2 | How it is built | 1:20 |
| 3 | What it does today | 4:53 |
| 4 | What could be next | 11:34 |

The figures on slide 3 -- specs, rules, test files and exercises -- are counted
from the repository when the deck is built, and the slide says on which day.

## Build it

The deck, with Node 20 or later, from this folder:

```bash
npm install          # once: pptxgenjs, and react-icons and sharp for the icons
node deck.js         # -> architecture.pptx
```

The video, from the repository root:

```bash
uv run playground/tutorial/architecture/narrate.py            # -> architecture.mp4 and .srt
uv run playground/tutorial/architecture/narrate.py --stills   # only the slides, as PNGs
```

`narrate.py` asks PowerPoint to draw each slide at 1920 x 1080 where it is
installed (Windows), and LibreOffice otherwise. It speaks the notes with Kokoro,
reusing `../render.py`'s voice and its cache of spoken sentences, so a second
run after editing one slide's notes only speaks that slide again. A first run
takes a few minutes for the speech; after that, mostly the encoding.

To change the video, edit `deck.js` and build both again, or edit the deck in
PowerPoint and run only `narrate.py`: it reads whatever deck it is given
(`narrate.py path/to/deck.pptx`). Write notes as they should read in the
subtitles: `PRONOUNCE` in `narrate.py` says how the voice reads a word such as
`MLflow` or `pipeline.yaml`, and never changes a caption.

## Three things found building it

- **PowerPoint refused a deck every validator passed.** A paragraph option
  (line spacing) on a text made of several runs makes pptxgenjs write the
  paragraph's properties before each run, inside the paragraph. A schema
  check of the file passed it; PowerPoint said only that it could not open
  the file, and one slide at a time found which. Exporting the slides through PowerPoint is the check, and
  `deck.js` sets no paragraph option on a text of runs.
- **pptxgenjs writes Office's palette into the theme**, so a theme colour
  would come out Office blue. `deck.js` writes its own colours over it after
  saving, which is why the deck can be restyled in one place: PowerPoint's
  Design tab, or `THEME` in `deck.js`.
- **The picture ran 29 seconds past the voice.** ffmpeg's concat list has to
  name its last picture twice, or the last duration is dropped, and the second
  naming then plays for as long again. `narrate.py` cuts the video at the
  narration's end. `../render.py` makes the quickstart the same way, and its
  video holds its last frame about three seconds past the voice for the same
  reason.

Nothing here is part of `dossier`, and nothing under `src/`, `tests/` or
`specs/` refers to it.
