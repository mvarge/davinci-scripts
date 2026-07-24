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
from .markers import MARKER_COLORS, add_marker, delete_markers, get_markers
from .fusion import find_tools_by_id, get_tool_inputs, set_tool_inputs

__all__ = [
    "ResolveConnectionError",
    "ResolveKit",
    "connect",
    "load_resolve_module",
    "MARKER_COLORS",
    "add_marker",
    "delete_markers",
    "get_markers",
    "find_tools_by_id",
    "get_tool_inputs",
    "set_tool_inputs",
]

__version__ = "0.1.0"
