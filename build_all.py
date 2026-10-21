"""Render every step and join them into one video per sequence.

    python build_all.py --disassembly --assembly                         # generated art, no SWF needed
    python build_all.py --art original --disassembly D.swf --assembly A.swf   # ETA's drawings: private use only
    python build_all.py --disassembly -q h                                # 1080p

Options:
  --art simple|original   simple (default): generated drawings, safe to publish.
                          original: ETA/tica's drawings from your SWF (give its path after
                          --disassembly / --assembly); never publish these videos.
  -q l|m|h     quality: 480p preview, 720p (default), 1080p
  --steps 3-9  only these steps (e.g. "1-5" or "4,8,35"); the joined file gets a _partial suffix
  --skip-prep  reuse the images already in assets/<art>/
  --no-titles  leave out the title card and the end credits (their text is in credits.yaml)

Writes renders/<art>/<sequence>_<quality>/stepNN.mp4 and 6497_<sequence>_<art>.mp4 in this
folder. A step is rendered again only when something it is made from has changed (the scene
code, that step's data, or its prepared images, e.g. after editing parts.yaml); otherwise the
clip from last time is reused. Delete renders/ to force a full rebuild.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QUALITY = {"l": ("-ql", "480p15"), "m": ("-qm", "720p30"), "h": ("-qh", "1080p60")}
SEQ = {"disassembly": ("steps.json", "DisassemblyStep", []),
       "assembly": ("assembly.json", "AssemblyStep", ["--assembly"])}


def parse_steps(spec, n):
    if not spec:
        return list(range(1, n + 1))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return [k for k in out if 1 <= k <= n]


def fingerprint(step, prefix, k, art):
    """hash of everything a step's clip is made from"""
    h = hashlib.sha256()
    h.update(open(os.path.join(HERE, "swisslab_step.py"), "rb").read())
    h.update(json.dumps(step, sort_keys=True).encode())
    for f in sorted(glob.glob(os.path.join(HERE, "assets", art, f"{prefix}{k:02d}_*"))):
        h.update(os.path.basename(f).encode())
        h.update(open(f, "rb").read())
    return h.hexdigest()


def card_fingerprint(seq, art, frame):
    """hash of everything the title card / end credits are made from"""
    h = hashlib.sha256((seq + art).encode())
    for f in ("swisslab_step.py", "credits.yaml", os.path.join("assets", art, "hero.png"), frame):
        f = os.path.join(HERE, f)
        if os.path.exists(f):
            h.update(open(f, "rb").read())
    return h.hexdigest()


def run(cmd, env=None):
    r = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True)
    if r.returncode:
        sys.stdout.write(r.stdout[-3000:] + r.stderr[-3000:])
        sys.exit(f"failed: {' '.join(cmd)}")
    return r


def build(seq, swf, args):
    data_file, scene, prep_flag = SEQ[seq]
    steps = json.load(open(os.path.join(HERE, data_file)))["steps"]
    todo = parse_steps(args.steps, len(steps))
    qflag, qdir = QUALITY[args.q]
    outdir = os.path.join(HERE, "renders", args.art, f"{seq}_{qdir}")
    os.makedirs(outdir, exist_ok=True)

    if not args.skip_prep:
        print(f"[{seq}] preparing {args.art} images for {len(todo)} steps ...")
        src = [swf] if args.art == "original" else []
        run([sys.executable, "-I", os.path.join("tools", "prep_assets.py"), *prep_flag, "--art", args.art,
             *src, "."] + [str(k) for k in todo])

    media = os.path.join(HERE, "media")

    def render(scene_name, clip, key, extra_env, label):
        """render one clip unless its fingerprint is unchanged; True if it was rendered"""
        keyfile = clip.replace(".mp4", ".key")
        old = open(keyfile).read().strip() if os.path.exists(keyfile) else None
        if os.path.exists(clip) and old == key:
            return False
        print(f"[{seq}] rendering {label}")
        env = dict(os.environ, CONTINUOUS="1", ART=args.art, SEQ=seq, **extra_env)
        name = f"{seq}_{args.art}_{os.path.basename(clip)[:-4]}"
        run([sys.executable, "-m", "manim", qflag, "--disable_caching", "--media_dir", media,
             "-o", name, "swisslab_step.py", scene_name], env=env)
        shutil.move(os.path.join(media, "videos", "swisslab_step", qdir, f"{name}.mp4"), clip)
        open(keyfile, "w").write(key + "\n")
        return True

    prefix = "asm" if seq == "assembly" else "step"
    clips, redone = [], 0
    for k in todo:
        clip = os.path.join(outdir, f"step{k:02d}.mp4")
        redone += render(scene, clip, fingerprint(steps[k - 1], prefix, k, args.art), {"STEP": str(k)},
                         f"step {k}/{len(steps)}: {steps[k - 1]['part']}")
        clips.append(clip)
    print(f"[{seq}] {redone} of {len(todo)} steps rendered, {len(todo) - redone} unchanged")

    if not args.no_titles:
        # the cards cross-fade from/into the very first and last frames of the steps
        first, last = os.path.join(outdir, "first_frame.png"), os.path.join(outdir, "last_frame.png")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", clips[0], "-frames:v", "1", first])
        run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.3", "-i", clips[-1], "-update", "1", last])
        cards = []
        for scene_name, stem, frame_var, frame in (("TitleCard", "title", "FIRST_FRAME", first),
                                                   ("EndCredits", "credits", "LAST_FRAME", last)):
            clip = os.path.join(outdir, f"{stem}.mp4")
            render(scene_name, clip, card_fingerprint(seq, args.art, frame), {frame_var: frame},
                   "title card" if stem == "title" else "end credits")
            cards.append(clip)
        clips = [cards[0]] + clips + [cards[1]]

    listfile = os.path.join(outdir, "clips.txt")
    with open(listfile, "w") as f:
        f.writelines(f"file '{c}'\n" for c in clips)
    final = os.path.join(HERE, f"6497_{seq}_{args.art}{'' if len(todo) == len(steps) else '_partial'}.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", final])
    print(f"[{seq}] wrote {final}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disassembly", metavar="SWF", nargs="?", const="", default=None,
                    help="build the disassembly video (the SWF path is needed only with --art original)")
    ap.add_argument("--assembly", metavar="SWF", nargs="?", const="", default=None,
                    help="build the assembly video (the SWF path is needed only with --art original)")
    ap.add_argument("--art", choices=("simple", "original"), default="simple")
    ap.add_argument("-q", choices="lmh", default="m")
    ap.add_argument("--steps")
    ap.add_argument("--skip-prep", action="store_true")
    ap.add_argument("--no-titles", action="store_true", help="leave out the title card and end credits")
    args = ap.parse_args()
    chosen = [seq for seq in ("disassembly", "assembly") if getattr(args, seq) is not None]
    if not chosen:
        ap.error("give --disassembly and/or --assembly")
    for seq in chosen:
        swf = getattr(args, seq)
        if args.art == "original" and not swf and not args.skip_prep:
            ap.error(f"--art original needs the SWF: --{seq} /path/to/the.swf")
    for seq in chosen:
        build(seq, getattr(args, seq), args)


if __name__ == "__main__":
    main()
