# davinci-scripts

[![tests](https://github.com/mvarge/davinci-scripts/actions/workflows/tests.yml/badge.svg)](https://github.com/mvarge/davinci-scripts/actions/workflows/tests.yml)

Python tooling for DaVinci Resolve:

- **`resolve_kit`** — a lean, zero-dependency helper library for scripting
  Resolve, designed for both humans and AI coding agents driving Resolve
  from prompts.
- **`drfx/`** — generators that build installable Resolve content from code:
  Fusion **transitions** (.drfx), Edit-page **effects** (.drfx), and
  creative **LUTs** (.cube).

## Requirements

- **DaVinci Resolve Studio** (the free edition does not allow external scripting)
- Resolve running, with **Preferences > General > External scripting using = Local**
- Python 3.10+ (no third-party dependencies — only Resolve's own scripting module)

Tested on macOS with Resolve 21. The module lookup also covers the default
Windows and Linux paths, and honors the `RESOLVE_SCRIPT_API` env var.

## Quick start

Check your connection:

```bash
python3 -m resolve_kit
```

```json
{
  "project": "My Project",
  "page": "edit",
  "timeline": "Timeline 1",
  "fps": 25.0,
  "video_tracks": 3,
  "audio_tracks": 4,
  "start_frame": 90000,
  "end_frame": 94018,
  "markers": 0
}
```

Use it in a script:

```python
from resolve_kit import connect, add_marker, get_markers, delete_markers

rk = connect()  # raises ResolveConnectionError with actionable hints

print(rk.project.GetName(), "@", rk.fps, "fps")

# iterate every clip on every video track
for track, item in rk.iter_video_items():
    print(f"V{track}: {item.GetName()} start={item.GetStart()}")

# markers (timeline-relative frames)
add_marker(rk.timeline, 100, color="Cyan", name="beat 1", note="[my-script]")
delete_markers(rk.timeline, note_contains="[my-script]")
```

## What's in `resolve_kit`

| Module | Contents |
|--------|----------|
| `connection` | `connect()` (local or `RESOLVE_SCRIPT_HOST` network mode), `ResolveKit` (lazy `project` / `timeline` / `media_pool` accessors, `is_alive()` / `reconnect()`, `save_state()` / `restore_state()`, iterators, `find_timeline`, `summary()`), cross-platform module discovery |
| `markers` | `get_markers`, `add_marker`, `delete_markers` — filterable by color / note / `custom_data`, `dry_run` previews, no-filter guard, color normalization, timecode input |
| `timecode` | `timecode_to_frames` / `frames_to_timecode` (incl. drop-frame and NTSC nominal rates), `parse_fps`, marker-frame rebasing (relative ↔ absolute) |
| `introspect` | `has_method` (the bridge fabricates callables — `hasattr` always lies), `verify_by_readback` (many setters return `True` regardless of effect) |
| `fusion` | `find_tools_by_id`, `first_tool_by_id`, `get_tool_inputs`, `set_tool_inputs(verify=...)` — e.g. for batch-editing Text+ tools |

Design principles:

- **Thin wrapper, not an abstraction layer.** `ResolveKit` hands you the raw
  API objects; helpers only remove boilerplate (path setup, null checks,
  track iteration).
- **Don't trust the API's return values.** Boolean success from Resolve
  setters is unreliable — use `verify_by_readback` and the pitfalls guide
  (`RESOLVE_SCRIPTING_GUIDE.md` > Known API Pitfalls).
- **Tag your writes.** Machine-generated markers should carry `custom_data`
  (invisible in the UI) so they can be found and reverted with
  `delete_markers(custom_data=...)`.
- **Verify after writing.** `rk.summary()` and the filterable getters make it
  cheap to confirm a change actually landed.

## Testing

```bash
# pure unit tests (no Resolve needed)
python3 -m pytest tests/test_timecode.py

# live smoke test — requires Resolve Studio running with a project open.
# Non-invasive by default (reversible marker ops, page switch + restore).
PYTHONPATH=. python3 tests/live_smoke.py

# --full additionally creates/deletes a disposable `_rk_test_*` project
# (switches your current project — save first)
PYTHONPATH=. python3 tests/live_smoke.py --full
```

## Utility scripts

- **`create_beat_markers.py`** — reads section markers named with beat counts
  (`6/4`, `10/8`, `4`) and fills in evenly-spaced beat sub-markers between
  them. Supports `--dry-run`, `--clear`, `--color`.
- **`export_beat_subtitles.py`** — reads the same time-signature markers and
  exports SRT files that put a bar+beat counter on screen (`6/4` over `3/4`),
  following every meter change. See
  [On-screen bar/beat counters](#on-screen-barbeat-counters) below.
- **`copy_text_style.py`** — copies the full visual style (font, shading
  elements, outline, shadow, spacing) from the first Text+ on the timeline to
  every other Text+, preserving each item's text. Supports `--dry-run`.

## On-screen bar/beat counters

Workflow for songs in shifting time signatures (a metronome/click timeline):
put a counter on screen that always shows the current bar's signature and which
beat of that bar you're on.

**1. Mark the bars.** One marker per bar, on the downbeat, with the marker
**name** set to that bar's time signature (`6/4`, `5/8`, `7/4`). The last marker
only terminates the previous bar and produces no captions.

**2. Optional — beat markers.** `create_beat_markers.py` fills in a sub-marker
per beat, useful for eyeballing the grid in the timeline. Not required by the
export; both scripts use identical subdivision arithmetic, so captions land
exactly on these markers.

**3. Export the SRTs.**

```bash
python3 export_beat_subtitles.py                    # two-track (recommended)
python3 export_beat_subtitles.py --layout two-line  # one file, two lines
python3 export_beat_subtitles.py --layout beats-only
python3 export_beat_subtitles.py --dry-run
```

Files land in `~/Desktop` by default (`--outdir` to change).

**4. Import.** Media Pool → right-click empty space → **Import Subtitle** →
pick the `.srt`. Then right-click the imported clip → **"Insert Selected
Subtitles to Timeline Using Timecode"** (manual PDF p. 1271). It decomposes
into individual captions, aligns by timecode, and creates the subtitle track.
Repeat for the second file in two-track mode; it lands on its own track.

**5. Style once.** Click the subtitle **track header** → Inspector → **Track**
panel. Font, size, colour, Position Y, Line Spacing, Drop Shadow, Stroke and
Background box apply to *every* caption on the track (manual PDF p. 1278).
Option menu (3 dots) → **Save Track as Preset** to reuse on the next song
(p. 1280).

### Why subtitle tracks, not Text+ titles

- Track-level styling restyles all captions at once. 255 Text+ clips would mean
  255 separate edits.
- No Fusion comp per caption, so the timeline stays responsive.
- `InsertFusionTitleIntoTimeline` cannot choose its target track anyway —
  `SetCurrentTrackIndex` passes `hasattr` but is not callable, and titles land
  on whichever track Resolve considers current. Subtitle import places by
  timecode instead.
- Titles also default to 250-frame durations, which would overlap wildly at
  9–18 frames per beat.

### Layout modes

| Mode | Files | On screen | Styling |
|------|-------|-----------|---------|
| `two-track` | 2 | `6/4` on ST1, `3/4` on ST2 | Each track styled independently — different size/colour/position per line |
| `two-line` | 1 | `6/4` newline `3/4` | One track; Line Spacing separates them, but both lines share size/colour |
| `beats-only` | 1 | `3/4` | Single track |

`two-track` is the default because per-line styling in `two-line` requires the
**Customize Caption** checkbox on each clip individually (manual PDF p. 1279),
which is impractical at hundreds of captions.

### Details that matter

- **Denominators are musical.** A 5/8 bar counts `1/8`–`5/8`; a 6/4 bar counts
  `1/4`–`6/4`. Not `1/5`.
- **Gap-free.** Each caption ends exactly where the next begins, so the counter
  never blinks out. The script validates this and reports any gap/overlap.
- **Absolute timecode.** SRT times are `marker frame + GetStartFrame()`, since
  marker frames are timeline-*relative* but subtitle import matches *absolute*
  timecode.
- **Remainder handling.** Beats divide by floor division with the remainder
  pushed onto the last intervals, so a 106-frame 6/4 bar gives
  `[17,17,18,18,18,18]` rather than drifting.

## Content generators (`drfx/`)

Installable Resolve content built from code — versionable, testable, and easy
to tweak (each transition/effect/look is a small Python function):

| Generator | Output | Install target |
|---|---|---|
| `make_pack.py` | "mvarge Essentials" — 7 Fusion transitions (Zoom/Spin Punch, Whip Pan ×4, Flash Cut) + optional film-burn transitions from local footage | `Fusion/Templates/` → Effects Library > Video Transitions |
| `make_effects.py` | "mvarge FX" — 5 Edit-page effects (Vignette, Letterbox 2.39, Film Grain, Chromatic Aberration, Punch Glow) | `Fusion/Templates/` → Effects Library > Effects |
| `make_luts.py` | "mvarge Looks" — 5 creative .cube LUTs (Punch, Film Fade, Teal Orange, Mono Crush, Cold Steel) | `LUT/` folder → LUT browser |

```bash
python3 drfx/make_pack.py --install      # transitions
python3 drfx/make_effects.py --install   # effects
python3 drfx/make_luts.py --install      # LUTs
```

Restart Resolve after installing .drfx packs (LUTs only need a "Refresh LUT
List"). The format spec lives in each generator's module docstring —
distilled from dissecting community packs plus ground-truth serializations
probed from a live Resolve via `resolve_kit`.

Key rules the generators enforce (and tests verify):

- Transitions animate exclusively via `time/comp.RenderEnd` so they rescale
  when trimmed on the timeline; effects are static.
- Stock Fusion tools only — no version-pinned ResolveFX OFX nodes.
- Transitions expose `MainInput1`/`MainInput2`/`MainOutput1`; effects expose
  a single `MainInput1`.

The film-burn transitions reference local media by absolute path (Fusion's
Loader can't decode HEVC, so burns are extracted to JPEG sequences); they're
skipped gracefully when the media isn't present.

## Scripting API docs

- `RESOLVE_SCRIPTING_GUIDE.md` — hands-on guide from real experimentation
  (setup, quirks, gotchas).
- `RESOLVE_API_REFERENCE.md` — condensed API reference for the objects used
  here (ProjectManager, Project, Timeline, TimelineItem, MediaPool, Fusion
  comps).

Blackmagic's official API README ships with Resolve at
`/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/README.txt`
(macOS).

## Using this repo with an AI coding agent

This repo is agent-friendly by design: an agent with shell access can drive
Resolve directly — no MCP server required. The loop:

1. `python3 -m resolve_kit` — verify connection and see current state.
2. Write a small script against `resolve_kit` + the API reference.
3. Run it (prefer `--dry-run` first for destructive changes).
4. Re-read state to verify the result.

See `AGENTS.md` for the full agent workflow used in this repo.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The short
version: every change ships with unit tests that pass without Resolve
(`python3 -m pytest tests/ --ignore=tests/live_smoke.py`), and content
generators must follow the format rules above.

## License

MIT — see [LICENSE](LICENSE). DaVinci Resolve is a trademark of Blackmagic
Design; this project is unaffiliated.
