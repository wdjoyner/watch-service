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
- **bridge**: a four-cornered plate around the arbors and screws it holds, laid out so bridges
  don't overlap and trimmed to the edge of the main plate (`corners:` and `avoid:` in
  `parts.yaml` adjust it)
- **plate**, **lever**, **spring**: simple placeholders for now

## Setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

Manim also needs Cairo, Pango and ffmpeg (see the comment in `requirements.txt`).

## Rendering a step (simple art)

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

The two extraction scripts also rewrite the fact files; on an unchanged SWF they come out
identical to the ones in the repository, so `git status` stays clean.

## Files

- `steps.json` / `.yaml`: the disassembly sequence
- `assembly.json` / `.yaml`: the assembly sequence (not a pure reversal), with the oiling points
  and the parts SwissLab hides when the movement is turned over
- `parts.json` / `.yaml`: the shared parts list, keyed by SwissLab's clip name (e.g. `MC31_046`),
  with `type`, `art` and `geom` for the generated drawings. `type` and `art` are edited by hand;
  `geom` and missing tooth/arm counts are filled in by `tools/measure_parts.py`.
- `swisslab_step.py`: the Manim scenes `DisassemblyStep` and `AssemblyStep` (env `STEP=n`,
  `ART=simple|original`)
- `tools/`: the SWF parser and renderer, the extraction and measuring scripts, the art generator
- `tests/smoke_test.py`: builds disassembly step 4 at 480p in simple art

## Test

    python tests/smoke_test.py

## Roadmap

- hand-made outlines for the plates, levers and springs
- oil symbols and detail drawings in simple art
- other SwissLab calibers (2824, 2892, 7750): generalize the turn-script index ranges and
  oil-symbol IDs that are specific to the 6497 files
