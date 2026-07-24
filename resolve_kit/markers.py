"""Marker helpers for timelines.

Resolve marker frames are relative to the timeline start (i.e. frame 0 is the
first frame of the timeline), while playhead timecode is absolute. These
helpers work in timeline-relative frames, matching Timeline.GetMarkers().
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# Colors accepted by Timeline.AddMarker (Resolve 18+).
MARKER_COLORS = [
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
]


def get_markers(timeline: Any, color: Optional[str] = None,
                note_contains: Optional[str] = None) -> dict[int, dict]:
    """Return {frame: marker_data}, optionally filtered by color and/or note."""
    markers = timeline.GetMarkers() or {}
    out = {}
    for frame, data in markers.items():
        if color and data.get("color") != color:
            continue
        if note_contains and note_contains not in data.get("note", ""):
            continue
        out[frame] = data
    return out


def add_marker(timeline: Any, frame: int, color: str = "Blue", name: str = "",
               note: str = "", duration: int = 1, custom_data: str = "") -> bool:
    """Add a marker at a timeline-relative frame. Returns False if occupied."""
    return bool(timeline.AddMarker(frame, color, name, note, duration, custom_data))


def delete_markers(timeline: Any, color: Optional[str] = None,
                   note_contains: Optional[str] = None,
                   predicate: Optional[Callable[[int, dict], bool]] = None) -> int:
    """Delete markers matching the filters; returns how many were removed.

    With no filters this deletes ALL markers — pass at least one filter unless
    that is really what you want.
    """
    count = 0
    for frame, data in list((timeline.GetMarkers() or {}).items()):
        if color and data.get("color") != color:
            continue
        if note_contains and note_contains not in data.get("note", ""):
            continue
        if predicate and not predicate(frame, data):
            continue
        if timeline.DeleteMarkerAtFrame(frame):
            count += 1
    return count
