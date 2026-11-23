# FlickMark

A raid target marker wheel for **World of Warcraft: Forever**. Hold a key, flick toward a marker, let go.

- **The direction picks the marker, at any distance.** Past a small centre, overshooting picks the same marker, so it
  never misses in a hurry.
- **Works the same in and out of combat.** Marks go through Blizzard's own secure marker action; nothing to switch on.
- **Picking the mark an enemy already has takes it off.** Letting go in the centre does nothing (or sets a skull, or
  removes the mark, if you like). Esc or right-click cancels.
- **Marks what you point at** when you press the key, else your target. In a fight it marks your target, or targets
  what you point at first if you turn that on.
- **Ground markers on a second key.** The same wheel, with the markers in the same places: let go on one, then click
  the ground where it goes. Picking a marker that's already down moves it.

Settings: Options > AddOns > FlickMark, or `/flickmark`. Choose the keys there.

## Working on it

The tests run the addon headless against a stand-in for the WoW API (Lua 5.1 through lupa):

```bash
pip install lupa pillow
python tests/run_flickmark.py
```

The harness runs FlickMark's real secure snippet in a stand-in for Blizzard's restricted environment.
`tools/make_flickmark_art.py` draws the wheel's textures in `Media/`.

Releases: push a tag like `v0.2.0`. The Release workflow builds the zip with the BigWigs packager and publishes
it on GitHub; the version in the `.toc` comes from the tag.

## License

MIT. See [LICENSE](LICENSE).
