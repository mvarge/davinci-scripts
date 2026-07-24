# davinci-scripts

Python scripting for DaVinci Resolve: a lean helper library (`resolve_kit`)
plus ready-to-use utility scripts. Designed for both humans and AI coding
agents driving Resolve from prompts.

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
| `connection` | `connect()`, `ResolveKit` (lazy `project` / `timeline` / `media_pool` accessors, `iter_video_items`, `iter_audio_items`, `iter_media_pool_clips`, `find_timeline`, `summary()`), cross-platform module discovery |
| `markers` | `get_markers`, `add_marker`, `delete_markers` — all filterable by color/note, `MARKER_COLORS` list |
| `fusion` | `find_tools_by_id`, `first_tool_by_id`, `get_tool_inputs`, `set_tool_inputs` — e.g. for batch-editing Text+ tools |

Design principles:

- **Thin wrapper, not an abstraction layer.** `ResolveKit` hands you the raw
  API objects; helpers only remove boilerplate (path setup, null checks,
  track iteration).
- **Tag your writes.** Scripts that create markers/objects should stamp them
  (e.g. a `note` prefix) so they can be found and reverted later — see
  `create_beat_markers.py` for the pattern.
- **Verify after writing.** `rk.summary()` and the filterable getters make it
  cheap to confirm a change actually landed.

## Utility scripts

- **`create_beat_markers.py`** — reads section markers named with beat counts
  (`6/4`, `10/8`, `4`) and fills in evenly-spaced beat sub-markers between
  them. Supports `--dry-run`, `--clear`, `--color`.
- **`copy_text_style.py`** — copies the full visual style (font, shading
  elements, outline, shadow, spacing) from the first Text+ on the timeline to
  every other Text+, preserving each item's text. Supports `--dry-run`.

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

## License

MIT — see [LICENSE](LICENSE). DaVinci Resolve is a trademark of Blackmagic
Design; this project is unaffiliated.
