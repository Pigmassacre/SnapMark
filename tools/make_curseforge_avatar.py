#!/usr/bin/env python3
"""Draws the CurseForge project avatar into curseforge/avatar.png: the AddOns list icon from make_snapmark_art.py,
filling the whole square (CurseForge rounds the corners itself).

    python3 tools/make_curseforge_avatar.py
"""

import os

from make_snapmark_art import icon

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "curseforge", "avatar.png")

SIZE = 512


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    icon(SIZE, corner=0).convert("RGB").save(OUT, optimize=True)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
