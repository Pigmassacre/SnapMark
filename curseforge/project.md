# CurseForge project fields

What to fill in when creating the SnapMark project on CurseForge. Not part of the addon zip.

- **Game / class:** World of Warcraft / Addons
- **Name:** SnapMark
- **Summary:** Hold a key, flick, release. A radial menu for target markers that never misses. Works in and out of combat. Supports ground markers too.
- **Main category:** Combat (Miscellaneous also fits)
- **License:** MIT License
- **Avatar:** `avatar.png` (512 × 512; redraw with `python3 tools/make_curseforge_avatar.py`)
- **Description:** paste `description.md`, with the editor set to Markdown
- **Screenshots:** take them in the game. The Preview button on the settings page shows the wheel without marking
  anything; one shot of the wheel open over a target with a slice lit up says the most.

After the project is created, put its ID in `SnapMark.toc` as `## X-Curse-Project-ID: <id>` and add the API token
to the GitHub repo as the `CF_API_KEY` secret. The Release workflow then uploads every `v*` tag.
