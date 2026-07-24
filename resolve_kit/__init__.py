"""resolve_kit — a lean helper library for scripting DaVinci Resolve in Python.

Usage:
    from resolve_kit import connect

    rk = connect()                     # raises ResolveConnectionError on failure
    print(rk.project.GetName())
    for item in rk.iter_video_items():
        print(item.GetName())

Requirements:
    - DaVinci Resolve running with a project open
    - Preferences > General > External scripting using > Local
    - Resolve Studio (the free edition does not allow external scripting)
"""

from .connection import (
    ResolveConnectionError,
    ResolveKit,
    connect,
    load_resolve_module,
)
from .markers import (
    MARKER_COLORS,
    add_marker,
    delete_markers,
    get_markers,
    normalize_marker_color,
)
from .fusion import find_tools_by_id, first_tool_by_id, get_tool_inputs, set_tool_inputs
from .introspect import ReadbackResult, has_method, verify_by_readback
from .timecode import (
    frames_to_timecode,
    marker_display_frame,
    nominal_fps,
    parse_fps,
    playhead_timecode_for_marker,
    rebase_to_timeline_start,
    timecode_to_frames,
)

__all__ = [
    "ResolveConnectionError",
    "ResolveKit",
    "connect",
    "load_resolve_module",
    "MARKER_COLORS",
    "add_marker",
    "delete_markers",
    "get_markers",
    "normalize_marker_color",
    "find_tools_by_id",
    "first_tool_by_id",
    "get_tool_inputs",
    "set_tool_inputs",
    "ReadbackResult",
    "has_method",
    "verify_by_readback",
    "frames_to_timecode",
    "marker_display_frame",
    "nominal_fps",
    "parse_fps",
    "playhead_timecode_for_marker",
    "rebase_to_timeline_start",
    "timecode_to_frames",
]

__version__ = "0.2.0"
