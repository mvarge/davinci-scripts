"""Timecode <-> frame conversion, and marker-frame rebasing.

Gotchas handled here (see RESOLVE_SCRIPTING_GUIDE.md "Known API Pitfalls"):

- Timeline marker frames are RELATIVE to the timeline start, while playhead
  timecode (Get/SetCurrentTimecode) is ABSOLUTE. AddMarker happily accepts
  absolute frames and GetMarkers echoes them back — but the marker is
  invisible in the UI. Use rebase_to_timeline_start / marker_display_frame.
- NTSC rates (23.976 / 29.97 / 59.94) use a nominal integer rate (24 / 30 /
  60) for timecode math.
- Drop-frame timecode uses ';' (or ',') separators and skips frame numbers;
  non-drop is assumed for parsing unless a ';' separator is present.
"""

from __future__ import annotations

import re
from typing import Any

_NTSC_NOMINAL = {
    23.976: 24, 23.98: 24,
    29.97: 30,
    47.952: 48, 47.95: 48,
    59.94: 60,
    119.88: 120,
}


def parse_fps(value: Any) -> float:
    """Parse a frame rate from int/float/str (Resolve settings return strings,
    occasionally with surrounding text). Raises ValueError if unparseable."""
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    if not match:
        raise ValueError(f"Cannot parse frame rate from {value!r}")
    fps = float(match.group(0))
    if fps <= 0:
        raise ValueError(f"Non-positive frame rate parsed from {value!r}")
    return fps


def nominal_fps(fps: float) -> int:
    """Integer timecode rate for a real frame rate (23.976 -> 24, etc.)."""
    for real, nominal in _NTSC_NOMINAL.items():
        if abs(fps - real) < 0.01:
            return nominal
    return round(fps)


def is_drop_frame_timecode(tc: str) -> bool:
    """Drop-frame timecodes conventionally use ';' (or ',') before frames."""
    return ";" in tc or "," in tc


def timecode_to_frames(tc: str, fps: float) -> int:
    """Convert 'HH:MM:SS:FF' (or drop-frame 'HH:MM:SS;FF') to a frame count."""
    parts = re.split(r"[:;,.]", tc.strip())
    if len(parts) != 4:
        raise ValueError(f"Invalid timecode {tc!r} (expected HH:MM:SS:FF)")
    hh, mm, ss, ff = (int(p) for p in parts)
    rate = nominal_fps(fps)

    if is_drop_frame_timecode(tc):
        # Drop-frame: 2 frames dropped per minute except every 10th minute
        # (4 for 59.94). Standard SMPTE conversion.
        drop = 2 * (rate // 30)
        total_minutes = hh * 60 + mm
        frames = (
            (hh * 3600 + mm * 60 + ss) * rate + ff
            - drop * (total_minutes - total_minutes // 10)
        )
        return frames
    return (hh * 3600 + mm * 60 + ss) * rate + ff


def frames_to_timecode(frames: int, fps: float, drop_frame: bool = False) -> str:
    """Convert a frame count to 'HH:MM:SS:FF' (non-drop unless requested)."""
    rate = nominal_fps(fps)
    if drop_frame:
        drop = 2 * (rate // 30)
        frames_per_10min = rate * 600 - drop * 9
        frames_per_min = rate * 60 - drop
        d, m = divmod(frames, frames_per_10min)
        if m > drop:
            frames += drop * 9 * d + drop * ((m - drop) // frames_per_min)
        else:
            frames += drop * 9 * d
        sep = ";"
    else:
        sep = ":"
    ff = frames % rate
    ss = (frames // rate) % 60
    mm = (frames // (rate * 60)) % 60
    hh = frames // (rate * 3600)
    return f"{hh:02d}:{mm:02d}:{ss:02d}{sep}{ff:02d}"


def rebase_to_timeline_start(timeline: Any, frame: int) -> int:
    """Convert an absolute frame (playhead domain) to a timeline-relative
    marker frame. Frames already below the timeline start are returned as-is
    (assumed already relative)."""
    start = timeline.GetStartFrame()
    if frame >= start:
        return frame - start
    return frame


def marker_display_frame(timeline: Any, marker_frame: int) -> int:
    """Convert a timeline-relative marker frame to the absolute frame used by
    SetCurrentTimecode / the playhead."""
    return timeline.GetStartFrame() + marker_frame


def playhead_timecode_for_marker(timeline: Any, marker_frame: int, fps: float) -> str:
    """Absolute timecode string to move the playhead onto a marker."""
    return frames_to_timecode(marker_display_frame(timeline, marker_frame), fps)
