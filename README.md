# watch-service

Step-by-step disassembly and assembly videos of mechanical watch movements, rendered with
[Manim](https://www.manim.community/). Each caliber has its own folder under `calibers/`:

| caliber | steps (disassembly / assembly) | source of the facts | status |
|---|---|---|---|
| `6497` — ETA 6497-1 / 6497-2, hand-wound | 37 / 37 | SwissLab SWF files | both videos build |
| `2892a2` — ETA 2892-A2, automatic, date | 60 / 60 | screen recording of SwissLab | facts extracted, part types tagged, sample steps rendered |

The step sequences come from ETA's SwissLab training animations (idea and animation: tica
international, www.tica.dk). This repository holds only facts read out of them, plus the code
that reads them and draws the videos:

- the order of the steps, and which side of the movement is up at each step
- each part's name, ETA catalog number, and (6497) whether it differs between the 6497-1 and 6497-2
- where each part sits and how it moves (positions, bounding boxes, motion)
- the oils and where they go

**No ETA or tica artwork is included.** The SWF files, recordings of SwissLab, and every
drawing extracted or rendered from them are ignored by git (see `.gitignore`). To see the
original drawings you need your own copy; see "Original art" below.

## Two art styles

| `--art simple` (default for publishing) | `--art original` (private use only) |
|---|---|
| Placeholder drawings generated from the facts in the caliber's `parts.yaml`, by `tools/simple_art.py`. Needs no SWF. Safe to publish. | ETA/tica's own drawings, rendered from your SWF on your computer. Do not publish videos made this way. Only for calibers whose facts come from SWFs. |

The generated drawings are built from each part's `type` and a few numbers, never traced:

- **wheel / pinion**: tooth count, radius, number of arms, tooth form (normal, ratchet, escape),
  and for reversing wheels and reversers the number of pawls around the hub (`pawls`)
- **screw**: head positions and size
- **jewel**, **balance** (rim, arms, hairspring, shock setting), **ring**, **stem**
- **rotor** (oscillating weight): a half-disc about the ball bearing with a heavy rim; its radius
  and direction are fitted to the measured bounding box. `see_through: true` draws it
  translucent (the whole automatic device on the movement)
- **date_ring** (date indicator): a flat ring with internal teeth and a tick for each date
  (numerals left out)
- **bridge**: a see-through, four-cornered plate around the arbors and screws it holds, laid
  out so bridges don't overlap and trimmed to the edge of the main plate (`corners:` and
  `avoid:` in `parts.yaml` adjust it). The wheels and pivots underneath stay visible.
- **plate** (a disc; `outline: box` for a unit's base plate seen by itself), **lever**,
  **spring**: simple placeholders for now

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Manim also needs Cairo, Pango and ffmpeg (see the comment in `requirements.txt`).

## Building the full videos

    python build_all.py --disassembly --assembly                     # the 6497 (default caliber)
    python build_all.py --caliber 2892a2 --disassembly --assembly    # the 2892-A2

This prepares the images, renders every step, and joins them into
`<caliber>_disassembly_simple.mp4` and `<caliber>_assembly_simple.mp4`. Each video opens with a
title card and closes with end credits; the steps flow into each other, with a card wherever
the movement is turned over or a unit is taken off and worked on by itself (the 2892-A2's
automatic device and barrel bridge). The text of the title card and the credits is in the
caliber's `credits.yaml`.

Options: `--caliber X` (a folder under `calibers/`, default `6497`), `-q l|m|h` (480p / 720p
default / 1080p), `--steps 1-10` (only some steps; the file gets a `_partial` suffix),
`--skip-prep` (reuse the prepared images), `--no-titles` (leave out the title card and
credits), `--art original` (see below).
Finished clips are kept in `renders/<caliber>/<art>/`. On the next run a step is rendered again
only if something it is made from has changed (for example after you edit `parts.yaml`); the
rest are reused. Delete `renders/` to force a full rebuild. Steps with several separately
moving screws, or no recorded motion, are shown with a simple fade.

## Rendering a single step (simple art)

    python -I tools/prep_assets.py --art simple calibers/6497 4
    ART=simple STEP=4 manim -qm swisslab_step.py DisassemblyStep

    python -I tools/prep_assets.py --art simple --assembly calibers/6497 35
    ART=simple STEP=35 manim -qm swisslab_step.py AssemblyStep

    python -I tools/prep_assets.py --art simple calibers/2892a2 20
    CALIBER=2892a2 ART=simple STEP=20 manim -qm swisslab_step.py DisassemblyStep

`-ql` renders at 480p, `-qm` at 720p, `-qh` at 1080p. Assembly steps in simple art don't show
the oil symbols or the edge-on detail drawings yet.

## Original art (private, SWF calibers only)

Put your SWFs somewhere outside the repository, then:

    python -I tools/steps.py          /path/to/6497disassem.swf calibers/6497   # drawings -> calibers/6497/parts/
    python -I tools/steps_assembly.py /path/to/6497assem.swf    calibers/6497   # drawings -> calibers/6497/parts_assembly/
    python -I tools/prep_assets.py /path/to/6497disassem.swf calibers/6497 4
    STEP=4 manim -qm swisslab_step.py DisassemblyStep

    # or the full videos (6497_disassembly_original.mp4, 6497_assembly_original.mp4):
    python build_all.py --art original --disassembly /path/to/6497disassem.swf --assembly /path/to/6497assem.swf

The two extraction scripts also rewrite the fact files; on an unchanged SWF they come out
identical to the ones in the repository, so `git status` stays clean.

## Adding a caliber

**From SwissLab SWFs.** SwissLab ships each caliber as a small menu file (e.g. `2892A2.swf`)
that loads `<caliber>disasm.swf`, `<caliber>asm.swf` and `<caliber>tools.swf`; the extraction
needs the disasm and asm files. Make `calibers/<slug>/` with a `caliber.yaml` (copy the 6497's)
and a `credits.yaml`, then fill in the `swisslab:` values with the help of

    python -I tools/inspect_swf.py /path/to/its.swf                       # what the SWF holds
    python -I tools/inspect_swf.py /path/to/its.swf --check calibers/<slug> # compare with caliber.yaml

It reports the step count, the frame labels and the steps after each (side up), the depth range
of the movement, note variables and oil-symbol IDs. Then run `steps.py`, `steps_assembly.py` and
`measure_parts.py`, and tag the part types in `parts.yaml`.

**From a screen recording of SwissLab** (when the SWFs are not available, as for the 2892-A2).
Write `calibers/<slug>/transcript.yaml` (what each screen says: step code, CS number, name,
side up, notes, and when each step starts and ends in the recording) and `catalog.yaml` (ETA's
parts list from the Technical Communication), then

    python -I tools/steps_video.py /path/to/recording.mp4 calibers/<slug> [--debug /some/folder/outside/the/repo]

It measures where each part sits, where SwissLab's arrow points, how the part moves, and where
oil marks appear, and writes the same fact files as the SWF tools. `--debug` writes one frame
per step with the measurements drawn on it, for checking (those frames show ETA's drawings: keep
them out of the repository).

## Files

- `calibers/<caliber>/`
  - `caliber.yaml`: name, output name, where the facts come from, and (SWF calibers) the values
    specific to that caliber's SWFs
  - `steps.json` / `.yaml`: the disassembly sequence
  - `assembly.json` / `.yaml`: the assembly sequence (not a pure reversal), with the oiling
    points; for the 6497 also the parts SwissLab hides when the movement is turned over
  - `parts.yaml`: the shared parts list, keyed by SwissLab's clip name (e.g. `MC31_046`), with
    `type`, `art` and `geom` for the generated drawings. **This is the file to edit**: `type`
    and `art` by hand; `geom` is measured (`hand: true` keeps a hand-set `geom` across
    re-extraction). `parts.json` is a generated copy for other programs.
  - `credits.yaml`: the wording of the title card and the end credits
  - 2892-A2 only: `transcript.yaml` (the screens, transcribed) and `catalog.yaml` (ETA's
    Technical Communications 2892-2 and 2892 A2, with the CS numbers)
- `swisslab_step.py`: the Manim scenes `DisassemblyStep` and `AssemblyStep` (env `CALIBER`,
  `STEP=n`, `ART=simple|original`, `CONTINUOUS=1` so the clips join seamlessly)
- `build_all.py`: renders every step and joins them into one video per sequence
- `tools/`: the SWF parser and renderer, the extraction and measuring scripts (SWF and
  recording), the SWF inspector, the art generator
- `tests/smoke_test.py`: builds disassembly step 4 at 480p in simple art
  (`python tests/smoke_test.py 2892a2` for another caliber)

## Test

    python tests/smoke_test.py
    python tests/smoke_test.py 2892a2

## Roadmap

- 2892-A2: tooth and arm counts (now estimates, marked `estimated: true`), oil types at each
  oil mark, outlines for the levers and the automatic-device frame; then the full videos
- hand-made outlines for the plates, levers and springs
- oil symbols and detail drawings in simple art
- other SwissLab calibers (2824, 7750)

## Credits

Written by David Joyner, with code developed together with Claude (Anthropic).

## License

The code and this repository's own files are released under the MIT License (see `LICENSE`).
The license does not cover the SwissLab SWF files, recordings of SwissLab, or any drawing
extracted or rendered from them: that artwork belongs to ETA / tica international and is not
part of this repository.
