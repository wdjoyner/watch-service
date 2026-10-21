# watch-service

Step-by-step disassembly and assembly videos of a mechanical watch movement, rendered with
[Manim](https://www.manim.community/). The first caliber is the ETA 6497-1/6497-2 hand-wound
movement, 37 steps each way.

The step sequences come from ETA's SwissLab training animations (two Flash files,
`6497disassem.swf` and `6497assem.swf`; idea and animation: tica international, www.tica.dk).
This repository holds only facts read out of those files, plus the code that reads them and
draws the videos:

- the order of the steps, and which side of the movement is up at each step
- each part's name in six languages, ETA catalog number, and whether it differs between the
  6497-1 and 6497-2
- where each part sits and how it moves (positions, bounding boxes, the SWF's motion keyframes)
- the oils (Moebius D5, 9010, 9501, 941) and where they go

**No ETA or tica artwork is included.** The SWF files, and every drawing extracted or rendered
from them, are ignored by git (see `.gitignore`). To see the original drawings you need your own
copy of the SWFs; see "Original art" below.

Part numbers are as given in ETA's technical communication for the 6497.

## Two art styles

| `--art simple` (default for publishing) | `--art original` (private use only) |
|---|---|
| Placeholder drawings generated from the facts in `parts.yaml`, by `tools/simple_art.py`. Needs no SWF. Safe to publish. | ETA/tica's own drawings, rendered from your SWF on your computer. Do not publish videos made this way. |

The generated drawings are built from each part's `type` and a few numbers, never traced from
the SWF:

- **wheel / pinion**: tooth count, radius, number of arms, tooth form (normal, ratchet, escape)
- **screw**: head positions and size
- **jewel**, **balance** (rim, arms, hairspring, shock setting), **ring**, **stem**
- **bridge**: a see-through, four-cornered plate around the arbors and screws it holds, laid
  out so bridges don't overlap and trimmed to the edge of the main plate (`corners:` and
  `avoid:` in `parts.yaml` adjust it). The wheels and pivots underneath stay visible.
- **plate**, **lever**, **spring**: simple placeholders for now

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Manim also needs Cairo, Pango and ffmpeg (see the comment in `requirements.txt`).

## Building the full videos

    python build_all.py --disassembly --assembly          # generated art, no SWF needed

This prepares the images, renders all 37 steps of each sequence, and joins them into
`6497_disassembly_simple.mp4` and `6497_assembly_simple.mp4` (about 5½ minutes each). Each video
opens with a title card and closes with end credits; the steps flow into each other, with a
"TURN MOVEMENT" card wherever the movement is turned over. The text of the title card and the
credits is in `credits.yaml`.

Options: `-q l|m|h` (480p / 720p default / 1080p), `--steps 1-10` (only some steps; the file
gets a `_partial` suffix), `--skip-prep` (reuse `assets/`), `--no-titles` (leave out the title card and credits),
`--art original` (see below).
Finished clips are kept in `renders/<art>/`. On the next run a step is rendered again only if
something it is made from has changed (for example after you edit `parts.yaml`); the rest are
reused. Delete `renders/` to force a full rebuild. Steps with several separately moving
screws, or no recorded motion, are shown with a simple fade.

## Rendering a single step (simple art)

    python -I tools/prep_assets.py --art simple . 4
    ART=simple STEP=4 manim -qm swisslab_step.py DisassemblyStep

    python -I tools/prep_assets.py --art simple --assembly . 35
    ART=simple STEP=35 manim -qm swisslab_step.py AssemblyStep

`-ql` renders at 480p, `-qm` at 720p, `-qh` at 1080p. Assembly steps in simple art don't show
the oil symbols or the edge-on detail drawings yet.

## Original art (private)

Put your SWFs somewhere outside the repository, then:

    python -I tools/steps.py          /path/to/6497disassem.swf .   # drawings -> parts/
    python -I tools/steps_assembly.py /path/to/6497assem.swf    .   # drawings -> parts_assembly/
    python -I tools/prep_assets.py /path/to/6497disassem.swf . 4
    STEP=4 manim -qm swisslab_step.py DisassemblyStep

    # or the full videos (6497_disassembly_original.mp4, 6497_assembly_original.mp4):
    python build_all.py --art original --disassembly /path/to/6497disassem.swf --assembly /path/to/6497assem.swf

The two extraction scripts also rewrite the fact files; on an unchanged SWF they come out
identical to the ones in the repository, so `git status` stays clean.

## Files

- `steps.json` / `.yaml`: the disassembly sequence
- `assembly.json` / `.yaml`: the assembly sequence (not a pure reversal), with the oiling points
  and the parts SwissLab hides when the movement is turned over
- `parts.yaml`: the shared parts list, keyed by SwissLab's clip name (e.g. `MC31_046`), with
  `type`, `art` and `geom` for the generated drawings. **This is the file to edit**: `type` and
  `art` by hand; `geom` and missing tooth/arm counts are filled in by `tools/measure_parts.py`.
  `parts.json` is a generated copy of it for other programs; the tools read `parts.yaml`.
- `swisslab_step.py`: the Manim scenes `DisassemblyStep` and `AssemblyStep` (env `STEP=n`,
  `ART=simple|original`, `CONTINUOUS=1` so the clips join seamlessly)
- `build_all.py`: renders every step and joins them into one video per sequence
- `credits.yaml`: the wording of the title card and the end credits
- `tools/`: the SWF parser and renderer, the extraction and measuring scripts, the art generator
- `tests/smoke_test.py`: builds disassembly step 4 at 480p in simple art

## Test

    python tests/smoke_test.py

## Roadmap

- hand-made outlines for the plates, levers and springs
- oil symbols and detail drawings in simple art
- other SwissLab calibers (2824, 2892, 7750): generalize the turn-script index ranges and
  oil-symbol IDs that are specific to the 6497 files

## Credits

Written by David Joyner, with code developed together with Claude (Anthropic).

## License

The code and this repository's own files are released under the MIT License (see `LICENSE`).
The license does not cover the SwissLab SWF files or any drawing extracted or rendered from
them: that artwork belongs to ETA / tica international and is not part of this repository.
