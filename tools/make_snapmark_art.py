#!/usr/bin/env python3
"""Draws SnapMark's art into SnapMark/Media as 32-bit TGA files.

White shapes on a transparent background, which the addon tints. The ring textures all cover the same square: the
whole wheel plus a margin for its shadow (RING_SPAN units across), so they can share one size and anchor in the game:

    ring    the wheel's backing, with a soft shadow outside
    rim     thin lines at the inner and outer edge and between the slices
    wedge   one slice, pointing up; the addon rotates it to the chosen marker
    notch   a small pointer on the centre's edge, pointing up; rotated to the way you move
    disc    the centre
    glow    a round soft glow, for behind the chosen marker
    icon    the AddOns list icon, in its own colors (also the CurseForge avatar)

    python3 tools/make_snapmark_art.py

Keep the numbers in step with Wheel.lua (R_IN, R_OUT, RING_SPAN).
"""

import math
import os
import struct

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "Media")

R_IN, R_OUT, RING_SPAN = 36, 116, 248  # in UI units, as in Wheel.lua
SIZE = 512
SS = 4  # supersampling


def write_tga(name, img):
    img = img.convert("RGBA")
    w, h = img.size
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 0x28)
    r, g, b, a = img.split()
    data = Image.merge("RGBA", (b, g, r, a)).tobytes()
    with open(os.path.join(OUT, name + ".tga"), "wb") as f:
        f.write(header)
        f.write(data)


def canvas(size=SIZE):
    return Image.new("L", (size * SS, size * SS), 0)


def unit(size=SIZE):
    """Pixels (supersampled) per UI unit, and the centre."""
    k = size * SS / RING_SPAN
    return k, size * SS / 2


def finish(mask, size=SIZE):
    mask = mask.resize((size, size), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    img.putalpha(mask)
    return img


def circle_box(c, r):
    return (c - r, c - r, c + r, c + r)


def ring():
    k, c = unit()
    shadow = canvas()
    d = ImageDraw.Draw(shadow)
    d.ellipse(circle_box(c, (R_OUT + 3) * k), fill=150)
    shadow = shadow.filter(ImageFilter.GaussianBlur(5 * k))
    body = canvas()
    d = ImageDraw.Draw(body)
    d.ellipse(circle_box(c, R_OUT * k), fill=255)
    d.ellipse(circle_box(c, R_IN * k), fill=0)
    hole = canvas()
    ImageDraw.Draw(hole).ellipse(circle_box(c, R_OUT * k), fill=255)
    # The shadow shows only outside the wheel; inside, the body decides.
    from PIL import ImageChops
    outside = ImageChops.subtract(shadow, hole)
    return finish(ImageChops.lighter(body, outside))


def rim():
    k, c = unit()
    m = canvas()
    d = ImageDraw.Draw(m)
    w = int(1.4 * k)
    d.ellipse(circle_box(c, R_OUT * k), outline=255, width=w)
    d.ellipse(circle_box(c, R_IN * k), outline=255, width=w)
    for i in range(8):
        a = math.radians(90 + 22.5 + i * 45)
        x0, y0 = c + math.cos(a) * (R_IN + 10) * k, c - math.sin(a) * (R_IN + 10) * k
        x1, y1 = c + math.cos(a) * (R_OUT - 10) * k, c - math.sin(a) * (R_OUT - 10) * k
        d.line([(x0, y0), (x1, y1)], fill=90, width=max(1, int(1.0 * k)))
    return finish(m)


def sector(d, c, k, r0, r1, half, fill, steps=48):
    pts = []
    for i in range(steps + 1):
        a = math.radians(90 - half + 2 * half * i / steps)
        pts.append((c + math.cos(a) * r1 * k, c - math.sin(a) * r1 * k))
    for i in range(steps, -1, -1):
        a = math.radians(90 - half + 2 * half * i / steps)
        pts.append((c + math.cos(a) * r0 * k, c - math.sin(a) * r0 * k))
    d.polygon(pts, fill=fill)


def wedge():
    k, c = unit()
    m = canvas()
    d = ImageDraw.Draw(m)
    r0, r1 = R_IN + 1.5, R_OUT - 1.5
    # Brighter towards the rim: thin bands from the inside out.
    bands = 40
    for i in range(bands):
        t0, t1 = i / bands, (i + 1) / bands
        sector(d, c, k, r0 + (r1 - r0) * t0, r0 + (r1 - r0) * t1 + 0.3, 22.5 - 1.2, int(255 * (0.22 + 0.33 * t1 ** 1.6)))
    sector(d, c, k, r1 - 3.5, r1, 22.5 - 1.2, 255)
    return finish(m)


def notch():
    k, c = unit(256)
    m = canvas(256)
    d = ImageDraw.Draw(m)
    tip, base, half = R_IN + 6, R_IN - 4, 7
    d.polygon([(c, c - tip * k), (c + half * k, c - base * k), (c - half * k, c - base * k)], fill=255)
    return finish(m, 256)


def disc():
    k, c = unit(256)
    m = canvas(256)
    ImageDraw.Draw(m).ellipse(circle_box(c, (R_IN - 2) * k), fill=255)
    return finish(m, 256)


def glow(size=128):
    img = Image.new("L", (size, size), 0)
    px = img.load()
    c = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            t = min(1.0, math.hypot(x - c, y - c) / (size / 2))
            px[x, y] = int(255 * (1 - t) ** 2.2)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.putalpha(img)
    return out


ICON_BG = (17, 21, 26)
# The eight markers' colours, clockwise from the top: skull, cross, square, moon, triangle, diamond, circle, star.
ICON_MARKS = [(240, 238, 230), (232, 72, 60), (66, 146, 240), (200, 212, 228), (84, 200, 96), (196, 98, 226),
              (242, 140, 48), (246, 208, 70)]


def _sector_points(c, r0, r1, a0, a1, steps=96):
    """An annular sector; angles in degrees, clockwise from the top."""
    out = [(c + math.sin(math.radians(a0 + (a1 - a0) * i / steps)) * r1,
            c - math.cos(math.radians(a0 + (a1 - a0) * i / steps)) * r1) for i in range(steps + 1)]
    out += [(c + math.sin(math.radians(a0 + (a1 - a0) * i / steps)) * r0,
             c - math.cos(math.radians(a0 + (a1 - a0) * i / steps)) * r0) for i in range(steps, -1, -1)]
    return out


def _round_corners(mask, r):
    """Blur, then cut at half: convex corners come out round."""
    return mask.filter(ImageFilter.GaussianBlur(r)).point(lambda v: 255 if v >= 128 else 0)


def icon(size=128, corner=0.22, pick=7):
    """The wheel reduced to its idea: one slice chosen and reaching past the rim (overshooting still picks it), with
    the marker's star cut out of it; the other markers are thin arcs of their colours. On a dark tile with round
    corners (corner=0 fills the square)."""
    S = size * SS
    c = S / 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    def mask():
        return Image.new("L", (S, S), 0)

    def paint(m, col):
        layer = Image.new("RGBA", (S, S), col + (255,))
        layer.putalpha(m)
        img.alpha_composite(layer)

    def mix(col, t):
        return tuple(int(ICON_BG[i] + (col[i] - ICON_BG[i]) * t) for i in range(3))

    m = mask()
    if corner:
        ImageDraw.Draw(m).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * corner), fill=255)
    else:
        m.paste(255, (0, 0, S, S))
    paint(m, ICON_BG)

    # The rim: an arc for every other marker, round at the ends.
    R, w, gap = S * 0.34, S * 0.028, 7
    for i, col in enumerate(ICON_MARKS):
        if i == pick:
            continue
        a0, a1 = i * 45 - 22.5 + gap, i * 45 + 22.5 - gap
        m = mask()
        d = ImageDraw.Draw(m)
        d.polygon(_sector_points(c, R - w / 2, R + w / 2, a0, a1), fill=255)
        for a in (a0, a1):
            x, y = c + math.sin(math.radians(a)) * R, c - math.cos(math.radians(a)) * R
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
        paint(m, mix(col, 0.7))

    # The chosen slice, past the rim, with an upright star cut out of it.
    from PIL import ImageChops
    m = mask()
    ImageDraw.Draw(m).polygon(_sector_points(c, S * 0.13, S * 0.45, pick * 45 - 18.5, pick * 45 + 18.5), fill=255)
    m = _round_corners(m, S * 0.012)
    a = math.radians(pick * 45)
    sx, sy, sr = c + math.sin(a) * S * 0.305, c - math.cos(a) * S * 0.305, S * 0.08
    star = mask()
    ImageDraw.Draw(star).polygon([(sx + math.sin(math.radians(k * 36)) * sr * (1 if k % 2 == 0 else 0.42),
                                   sy - math.cos(math.radians(k * 36)) * sr * (1 if k % 2 == 0 else 0.42))
                                  for k in range(10)], fill=255)
    paint(ImageChops.subtract(m, _round_corners(star, sr * 0.04)), ICON_MARKS[pick])

    # The centre.
    m = mask()
    ImageDraw.Draw(m).ellipse(circle_box(c, S * 0.055), fill=255)
    paint(m, (242, 240, 232))
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (("ring", ring), ("rim", rim), ("wedge", wedge), ("notch", notch), ("disc", disc),
                     ("glow", glow), ("icon", icon)):
        write_tga(name, fn())
        print("Wrote", name)


if __name__ == "__main__":
    main()
