#!/usr/bin/env python3
"""Draws MarkWheel's art into MarkWheel/Media as 32-bit TGA files.

White shapes on a transparent background, which the addon tints. The ring textures all cover the same square: the
whole wheel plus a margin for its shadow (RING_SPAN units across), so they can share one size and anchor in the game:

    ring    the wheel's backing, with a soft shadow outside
    rim     thin lines at the inner and outer edge and between the slices
    wedge   one slice, pointing up; the addon rotates it to the chosen marker
    notch   a small pointer on the centre's edge, pointing up; rotated to the way you move
    disc    the centre
    glow    a round soft glow, for behind the chosen marker
    icon    the AddOns list icon, in its own colors

    python3 tools/make_markwheel_art.py

Keep the numbers in step with Wheel.lua (R_IN, R_OUT, RING_SPAN).
"""

import math
import os
import struct

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "MarkWheel", "Media")

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


def icon(size=64):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = S / 2
    d.ellipse(circle_box(c, S * 0.47), fill=(22, 26, 30, 255))
    d.ellipse(circle_box(c, S * 0.47), outline=(120, 130, 140, 255), width=SS * 2)
    colors = [(242, 242, 236), (232, 68, 58), (63, 142, 240), (201, 214, 230), (79, 201, 90), (194, 94, 224),
              (240, 138, 44), (245, 209, 66)]
    for i, col in enumerate(colors):
        a = math.radians(90 - i * 45)
        x, y = c + math.cos(a) * S * 0.31, c - math.sin(a) * S * 0.31
        d.ellipse(circle_box(x, S * (0.085 if i else 0.11)), fill=col + (255,))
    # The chosen slice: a pointer from the centre towards the skull.
    d.polygon([(c, c - S * 0.17), (c + S * 0.07, c - S * 0.04), (c - S * 0.07, c - S * 0.04)], fill=(242, 242, 236, 255))
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, fn in (("ring", ring), ("rim", rim), ("wedge", wedge), ("notch", notch), ("disc", disc),
                     ("glow", glow), ("icon", icon)):
        write_tga(name, fn())
        print("Wrote", name)


if __name__ == "__main__":
    main()
