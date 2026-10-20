"""One SwissLab step as a Manim scene, driven by steps.json (disassembly) or
assembly.json (assembly).

    python -I tools/prep_assets.py --art simple . 4                  # generated drawings, no SWF
    ART=simple STEP=4 manim -qm swisslab_step.py DisassemblyStep

    python -I tools/prep_assets.py 6497disassem.swf . 4              # assets/original/step04_*.png
    STEP=4 manim -qm swisslab_step.py DisassemblyStep

    python -I tools/prep_assets.py --assembly 6497assem.swf . 35     # assets/original/asm35_*.png
    STEP=35 manim -qm swisslab_step.py AssemblyStep

ART=original (default) uses ETA/tica's drawings from your SWF, for private use only.
ART=simple uses the generated placeholder drawings, which can be published.

Geometry and motion come straight from the SWFs. Disassembly: the part is
highlighted as SwissLab does it (yellow wash, red outline), then follows the
SWF's tween keyframes into the right-hand panel. Assembly: the part flies in
from the panel along the assembly SWF's keyframes, then the oiling points
appear, with the oils named in the panel.
"""
import json
import os

from manim import (DOWN, LEFT, UP, FadeIn, FadeOut, ImageMobject, Rectangle, Scene, Text, VGroup,
                   linear, there_and_back)

HERE = os.path.dirname(os.path.abspath(__file__))
STEP = int(os.environ.get("STEP", 4))
ART = os.environ.get("ART", "original")
ASSETS = os.path.join(HERE, "assets", ART)
# CONTINUOUS=1 (set by build_all.py): the frame stays on screen and each clip starts exactly
# where the previous one ended, so the clips join seamlessly into one video
CONTINUOUS = os.environ.get("CONTINUOUS") == "1"
SPEED = 0.5            # SwissLab plays at 12 fps; 0.5 = twice as slow, easier to follow
FPS_SWF = 12

# SwissLab stage (800 x 600 px) -> Manim units
K = 0.0172                       # units per stage px
CX, CY = 400, 312                # stage point that maps to the Manim origin
WINDOW = [18, 122, 432, 512]     # movement window (stage px)
PANEL = [444, 122, 782, 512]     # info panel
PARTBOX = [472, 275, 755, 498]   # lower box where parts are shown

BG = "#1e1e1e"
INK = "#202020"
MUTED = "#6b6b6b"
MARK_YELLOW = "#ffff22"          # SwissLab's highlight colors
MARK_RED = "#ff2211"


def S(x, y):
    """stage px -> Manim point"""
    return [(x - CX) * K, -(y - CY) * K, 0]


def stage_rect(r, **kw):
    x0, y0, x1, y1 = r
    rect = Rectangle(width=(x1 - x0) * K, height=(y1 - y0) * K, **kw)
    rect.move_to(S((x0 + x1) / 2, (y0 + y1) / 2))
    return rect


def stage_image(path, bbox):
    x0, y0, x1, y1 = bbox
    img = ImageMobject(path)
    img.height = (y1 - y0) * K
    img.move_to(S((x0 + x1) / 2, (y0 + y1) / 2))
    return img


def _wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "\n".join(lines)


def T(text, size, color=INK, weight="NORMAL"):
    return Text(text, font="Inter", weight=weight, color=color, line_spacing=0.8).scale(size)


class _StepScene(Scene):
    DATA = "steps.json"
    PREFIX = "step"
    TITLE = "ETA 6497 · disassembly"
    PART_AT_START = True       # disassembly: the part is in the movement when the step starts

    def end_step(self, leaving=()):
        """clear this step's text (and anything listed) so the next clip can start clean"""
        if CONTINUOUS:
            gone = [self.info] + ([self.extras] if len(self.extras) else []) + list(leaving)
            self.play(*[FadeOut(m) for m in gone], run_time=0.5)

    def setup_step(self):
        data = json.load(open(os.path.join(HERE, self.DATA)))
        self.steps = data["steps"]
        s = self.s = self.steps[STEP - 1]
        self.camera.background_color = BG

        window = stage_rect(WINDOW, stroke_width=0, fill_color="#ffffff", fill_opacity=1)
        panel = stage_rect(PANEL, stroke_width=0, fill_color="#ffffff", fill_opacity=1)
        self.partbox = stage_rect(PARTBOX, stroke_color="#c8c8c8", stroke_width=1.5)
        title = T(self.TITLE, 0.5, "#e8e8e8", "MEDIUM").move_to(S(400, 92))
        bg = ImageMobject(os.path.join(ASSETS, f"{self.PREFIX}{STEP:02d}_bg.png"))
        bg.height = (WINDOW[3] - WINDOW[1]) * K
        bg.move_to(window)

        x_text = S(PANEL[0] + 22, 0)[0]
        name = T(s["part"], 0.42, weight="MEDIUM")
        if name.width > (PANEL[2] - PANEL[0] - 44) * K:
            name = T(_wrap(s["part"], 28), 0.42, weight="MEDIUM")
        cat = s.get("catalog_no")
        info = VGroup(T(f"Step {STEP} of {len(self.steps)}", 0.32, MUTED), name,
                      T(f"Catalog no. {cat}" if cat and cat[0].isdigit() else "Catalog no. —", 0.3, MUTED),
                      T(f"{s['side_up'].capitalize()} side up", 0.3, MUTED))
        info.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        info.move_to(S(0, 150), aligned_edge=UP).set_x(x_text, direction=LEFT)
        self.info = info
        extras = VGroup()
        if s.get("differs_6497_1_vs_2"):
            extras.add(T("⚠ differs between 6497-1 and 6497-2", 0.27, "#b25a00"))
        if s.get("note"):
            extras.add(T(_wrap(s["note"], 46), 0.25, "#b00020"))
        if len(extras):
            extras.arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(info, DOWN, buff=0.2, aligned_edge=LEFT)
        self.extras = extras

        part_png = os.path.join(ASSETS, f"{self.PREFIX}{STEP:02d}_part.png")
        meta = part_png.replace(".png", ".json")      # generated art: padded image, tight highlight box
        meta = json.load(open(meta)) if os.path.exists(meta) else {}
        self.part_bbox = meta.get("image_bbox", s["bbox_stage_px"])
        self.highlight_bbox = meta.get("highlight_bbox", s["bbox_stage_px"])
        self.part = stage_image(part_png, self.part_bbox)
        self.bg = bg
        start_with = [bg] + ([self.part] if self.PART_AT_START else [])
        turned = STEP > 1 and self.steps[STEP - 2]["side_up"] != s["side_up"]
        if CONTINUOUS:
            self.add(window, panel, title, self.partbox)
            if turned:
                # SwissLab's "TURN MOVEMENT" moment
                card = T("TURN MOVEMENT", 0.55, INK, "MEDIUM").move_to(window)
                sub = T(f"{s['side_up'].capitalize()} side up", 0.32, MUTED).next_to(card, DOWN, buff=0.15)
                self.play(FadeIn(card, scale=0.9), FadeIn(sub), run_time=0.6)
                self.wait(0.8)
                self.play(FadeOut(card), FadeOut(sub), run_time=0.4)
                self.play(*[FadeIn(m) for m in start_with], run_time=0.8)
            else:
                self.add(*start_with)
        else:
            self.play(FadeIn(window), FadeIn(panel), FadeIn(title), run_time=0.6)
            self.play(*[FadeIn(m) for m in start_with], FadeIn(self.partbox), run_time=0.8)
        self.play(FadeIn(info, shift=0.1 * UP), run_time=0.6)
        if len(extras):
            self.play(FadeIn(extras), run_time=0.4)

    def follow_motion(self):
        """the SWF's own tween, phase by phase (Flash tweens are linear)"""
        for ph in self.s["motion"]:
            tx, ty, sc_to = ph["to"]
            self.play(self.part.animate.move_to(S(tx, ty)).scale(sc_to / ph["from"][2]),
                      run_time=ph["frames"] / FPS_SWF / SPEED, rate_func=linear)


class DisassemblyStep(_StepScene):
    def construct(self):
        self.setup_step()
        part, s = self.part, self.s
        # SwissLab highlight: yellow wash pulsing to 60% inside a red outline (bounds - 2 px)
        x0, y0, x1, y1 = self.highlight_bbox
        hb = [x0 - 2, y0 - 2, x1, y1]
        wash = stage_rect(hb, stroke_width=0, fill_color=MARK_YELLOW, fill_opacity=0.6)
        outline = stage_rect(hb, stroke_color=MARK_RED, stroke_width=2.5)
        self.play(FadeIn(outline), run_time=0.3)
        for _ in range(2):
            self.play(FadeIn(wash, rate_func=there_and_back), run_time=1.0)
        self.remove(wash)
        self.wait(0.3)
        self.play(FadeOut(outline), run_time=0.3)
        self.bring_to_front(part)
        if s["motion"]:
            self.follow_motion()
            self.wait(1.5)
            self.end_step([part])
        else:
            # several pieces moving separately (or no recorded motion): lift it out with a fade
            self.play(FadeOut(part, shift=0.25 * UP), run_time=1.0)
            self.wait(0.6)
            self.end_step()


class AssemblyStep(_StepScene):
    """SwissLab's order: the part waits in the panel (with an edge-on detail drawing for some
    parts) while the oil symbols show where to oil; then the symbols clear and the part is fitted."""
    DATA = "assembly.json"
    PREFIX = "asm"
    TITLE = "ETA 6497 · assembly"
    PART_AT_START = False      # assembly: the part arrives during the step

    def construct(self):
        self.setup_step()
        part, s = self.part, self.s
        rest = part
        waiting = []
        if s["motion"]:
            # fly the unmasked drawing from the shared parts list (if there is one), then swap in
            # the in-place drawing, whose mask tucks it under neighboring parts
            free_png = os.path.join(ASSETS, f"asm{STEP:02d}_free.png")
            if os.path.exists(free_png):
                fb = json.load(open(free_png.replace(".png", ".json")))
                self.part = part = stage_image(free_png, fb)
                part.shift([a - b for a, b in zip(rest.get_center(), part.get_center())])
            fx, fy, fs = s["motion"][0]["from"]          # where the SWF parks it, in the panel
            part.scale(fs).move_to(S(fx, fy))
        waiting.append(part)
        detail_png = os.path.join(ASSETS, f"asm{STEP:02d}_detail.png")
        if s.get("detail_bbox_stage_px") and os.path.exists(detail_png):    # not generated for simple art yet
            waiting.append(stage_image(detail_png, s["detail_bbox_stage_px"]))
        self.play(*[FadeIn(m) for m in waiting], run_time=0.6)

        clear = [m for m in waiting if m is not part]
        oil_png = os.path.join(ASSETS, f"asm{STEP:02d}_oil.png")
        if s.get("oil_bbox_stage_px") and os.path.exists(oil_png):          # not generated for simple art yet
            oil = stage_image(oil_png, s["oil_bbox_stage_px"])
            kinds = []
            for o in s["oil"]:
                if o["type"].startswith("Moebius") and o["type"] not in kinds:
                    kinds.append(o["type"])
            counts = {k: sum(o["type"] == k for o in s["oil"]) for k in kinds}
            # one line under the panel, so it never covers the part or the detail drawing
            items = [f"{k} ({counts[k]} point{'s' if counts[k] > 1 else ''})" for k in kinds]
            key = T("Oiling:  " + "   ·   ".join(items), 0.3, "#ff8a80")
            if key.width > (PANEL[2] - PANEL[0]) * K:          # too long: shrink to the panel's width
                key.scale_to_fit_width((PANEL[2] - PANEL[0]) * K)
            key.move_to(S(PANEL[0], PANEL[3] + 17), aligned_edge=LEFT)
            self.wait(0.3)
            self.play(FadeIn(oil), FadeIn(key, shift=0.1 * UP), run_time=0.8)
            clear += [oil, key]
            self.wait(2.0)
        else:
            self.wait(1.2)
        if clear:
            self.play(*[FadeOut(m) for m in clear], run_time=0.5)
        if s["motion"]:
            self.follow_motion()
            if part is not rest:
                self.remove(part)
                self.add(rest)
        self.wait(1.5)
        self.end_step()
