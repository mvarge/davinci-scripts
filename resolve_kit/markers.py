"""Marker helpers for timelines.

Resolve marker frames are relative to the timeline start (i.e. frame 0 is the
first frame of the timeline), while playhead timecode is absolute. AddMarker
happily accepts absolute frames and GetMarkers echoes them back — but such
markers are INVISIBLE in the UI. These helpers work in timeline-relative
frames, matching Timeline.GetMarkers(); use `rebase=True` (or the timecode
module) when starting from playhead/absolute positions.

For machine-generated markers prefer tagging via `custom_data` (invisible in
the UI, keeps user-facing notes clean) over note prefixes.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from .timecode import rebase_to_timeline_start, timecode_to_frames

# Colors accepted by Timeline.AddMarker (Resolve 18+).
MARKER_COLORS = [
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
]

_COLOR_LOOKUP = {c.lower(): c for c in MARKER_COLORS}


def normalize_marker_color(color: str) -> str:
    """Case-insensitive match against the canonical color list."""
    canonical = _COLOR_LOOKUP.get(color.strip().lower())
    if canonical is None:
        raise ValueError(
            f"Unknown marker color {color!r}. Valid: {', '.join(MARKER_COLORS)}"
        )
    return canonical


def _match(data: dict, color: Optional[str], note_contains: Optional[str],
           custom_data: Optional[str]) -> bool:
    if color and data.get("color") != color:
        return False
    if note_contains and note_contains not in data.get("note", ""):
        return False
    if custom_data and data.get("customData", "") != custom_data:
        return False
    return True


def get_markers(timeline: Any, color: Optional[str] = None,
                note_contains: Optional[str] = None,
                custom_data: Optional[str] = None) -> dict[int, dict]:
    """Return {frame: marker_data}, filtered by color/note/custom_data."""
    if color:
        color = normalize_marker_color(color)
    markers = timeline.GetMarkers() or {}
    return {
        frame: data for frame, data in markers.items()
        if _match(data, color, note_contains, custom_data)
    }


def add_marker(timeline: Any, frame: Union[int, str], color: str = "Blue",
               name: str = "", note: str = "", duration: int = 1,
               custom_data: str = "", rebase: bool = False) -> bool:
    """Add a marker. Returns False if the frame is occupied.

    frame  — timeline-relative frame (int), or a timecode string
             ('HH:MM:SS:FF', absolute — converted automatically).
    rebase — treat an int frame as absolute and rebase it to timeline start.
             Guards against the invisible-marker trap when working from
             playhead positions.
    """
    color = normalize_marker_color(color)
    if isinstance(frame, str):
        from .timecode import parse_fps

        fps = parse_fps(timeline.GetSetting("timelineFrameRate"))
        frame = rebase_to_timeline_start(timeline, timecode_to_frames(frame, fps))
    elif rebase:
        frame = rebase_to_timeline_start(timeline, frame)
    return bool(timeline.AddMarker(frame, color, name, note, duration, custom_data))


def delete_markers(timeline: Any, color: Optional[str] = None,
                   note_contains: Optional[str] = None,
                   custom_data: Optional[str] = None,
                   predicate: Optional[Callable[[int, dict], bool]] = None,
                   dry_run: bool = False,
                   allow_all: bool = False) -> dict[int, dict]:
    """Delete markers matching the filters; returns the affected markers
    as {frame: marker_data} (with dry_run=True, what WOULD be deleted).

    Safety: with no filters at all, this refuses to run unless allow_all=True
    (deleting every marker on the timeline is rarely what you want).
    """
    if not any([color, note_contains, custom_data, predicate]) and not allow_all:
        raise ValueError(
            "delete_markers called with no filters — this would delete ALL "
            "markers. Pass a filter, or allow_all=True if intentional."
        )
    if color:
        color = normalize_marker_color(color)

    affected: dict[int, dict] = {}
    for frame, data in list((timeline.GetMarkers() or {}).items()):
        if not _match(data, color, note_contains, custom_data):
            continue
        if predicate and not predicate(frame, data):
            continue
        if dry_run or timeline.DeleteMarkerAtFrame(frame):
            affected[frame] = data
    return affected
