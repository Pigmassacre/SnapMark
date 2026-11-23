#!/usr/bin/env python3
"""Draws the CurseForge gallery images into curseforge/screenshots/ from the in-game shots in
curseforge/screenshots/source/: each shot large on the right, a headline and three points on the left, on the dark
of the icon.

    python3 tools/make_curseforge_shots.py

Needs Pillow and the Outfit font (~/.local/share/fonts/Outfit-VariableFont_wght.ttf, or set OUTFIT to its path).
"""

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from make_snapmark_art import ICON_BG, ICON_MARKS, icon

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "curseforge", "screenshots", "source")
OUT = os.path.join(ROOT, "curseforge", "screenshots")
FONT = os.environ.get("OUTFIT", os.path.expanduser("~/.local/share/fonts/Outfit-VariableFont_wght.ttf"))

W, H = 1600, 900
SS = 2  # drawn at twice the size, then scaled down
TEXT = (242, 240, 232)
MUTED = (160, 170, 180)
STAR, CROSS, SQUARE, TRIANGLE = ICON_MARKS[7], ICON_MARKS[1], ICON_MARKS[2], ICON_MARKS[4]

SHOTS = [
    {
        "out": "1-hold-a-key.png",
        "src": "wheel-open.png",
        "title": ["Hold a key."],
        "text": "The wheel opens right at your cursor, with all eight raid markers.",
        "points": [(STAR, "Marks your mouseover, or your target"), (CROSS, "Works in and out of combat"),
                   (SQUARE, "Ground markers on a second key")],
    },
    {
        "out": "2-flick-release.png",
        "src": "wheel-cross.png",
        "title": ["Flick. Release.", "Marked."],
        "text": "It picks by direction, not distance. Overshoot as far as you like and it still picks the right one.",
        "points": [(STAR, "The marker's name shows before you let go"), (CROSS, "Pick it again to clear the mark"),
                   (TRIANGLE, "Esc or right-click cancels")],
    },
]


def font(size, weight):
    f = ImageFont.truetype(FONT, size * SS)
    f.set_variation_by_name(weight)
    return f


def wrap(draw, text, f, width):
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if draw.textlength(test, font=f) <= width:
            line = test
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def background():
    """The icon's dark, with a soft light behind the shot."""
    S = (W * SS, H * SS)
    img = Image.new("RGBA", S, ICON_BG + (255,))
    glow = Image.new("L", S, 0)
    cx, cy, r = 1110 * SS, 450 * SS, 520 * SS
    ImageDraw.Draw(glow).ellipse((cx - r, cy - r, cx + r, cy + r), fill=40)
    glow = glow.filter(ImageFilter.GaussianBlur(160 * SS))
    img.paste((70, 90, 110, 255), (0, 0), glow)
    return img


def framed(shot, height):
    """The shot scaled to height, with round corners, a hairline edge and a shadow. Returns it and its shadow."""
    k = height * SS / shot.height
    w, h = round(shot.width * k), round(shot.height * k)
    shot = shot.convert("RGBA").resize((w, h), Image.LANCZOS)
    radius = 22 * SS
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    shot.putalpha(mask)
    ImageDraw.Draw(shot).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=(255, 255, 255, 40),
                                           width=2 * SS)
    pad = 60 * SS
    shadow = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 14 * SS, pad + w, pad + h + 14 * SS), radius=radius,
                                             fill=(0, 0, 0, 170))
    return shot, shadow.filter(ImageFilter.GaussianBlur(26 * SS)), pad


def make(spec):
    img = background()
    d = ImageDraw.Draw(img)

    # The shot, on the right.
    shot, shadow, pad = framed(Image.open(os.path.join(SRC, spec["src"])), 720)
    sx, sy = (1600 - 90) * SS - shot.width, (H * SS - shot.height) // 2
    img.alpha_composite(shadow, (sx - pad, sy - pad))
    img.alpha_composite(shot, (sx, sy))

    # The name, top left.
    x = 96 * SS
    mark = icon(64 * SS, corner=0.24)
    img.alpha_composite(mark, (x, 84 * SS))
    d.text((x + 84 * SS, 84 * SS + 32 * SS), "SnapMark", font=font(40, b"Bold"), fill=TEXT, anchor="lm")

    # Headline, text and points, centred on the left as a block.
    title_f, text_f, point_f = font(84, b"Black"), font(30, b"Medium"), font(28, b"SemiBold")
    width = sx - x - 70 * SS
    text_lines = wrap(d, spec["text"], text_f, width)
    title_h, text_h, point_h = 92 * SS, 42 * SS, 52 * SS
    block = len(spec["title"]) * title_h + 26 * SS + len(text_lines) * text_h + 40 * SS + len(spec["points"]) * point_h
    y = (H * SS - block) // 2 + 40 * SS
    for line in spec["title"]:
        d.text((x - 4 * SS, y), line, font=title_f, fill=TEXT)
        y += title_h
    y += 26 * SS
    for line in text_lines:
        d.text((x, y), line, font=text_f, fill=MUTED)
        y += text_h
    y += 40 * SS
    for col, label in spec["points"]:
        r = 9 * SS
        cy = y + 18 * SS
        d.ellipse((x, cy - r, x + 2 * r, cy + r), fill=col + (255,))
        d.text((x + 2 * r + 18 * SS, cy), label, font=point_f, fill=TEXT, anchor="lm")
        y += point_h

    out = img.resize((W, H), Image.LANCZOS).convert("RGB")
    path = os.path.join(OUT, spec["out"])
    out.save(path, optimize=True)
    print("Wrote", path)


def main():
    os.makedirs(OUT, exist_ok=True)
    for spec in SHOTS:
        make(spec)


if __name__ == "__main__":
    main()
