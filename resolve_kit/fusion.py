"""Fusion comp helpers — e.g. for working with Text+ (TextPlus) tools."""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Optional


def find_tools_by_id(item: Any, tool_id: str = "TextPlus") -> Iterator[tuple[Any, Any]]:
    """Yield (tool, comp) pairs for every tool with the given ID across all
    Fusion comps of a timeline item."""
    for i in range(1, (item.GetFusionCompCount() or 0) + 1):
        comp = item.GetFusionCompByIndex(i)
        if not comp:
            continue
        for _, tool in (comp.GetToolList() or {}).items():
            if tool.ID == tool_id:
                yield tool, comp


def first_tool_by_id(item: Any, tool_id: str = "TextPlus") -> tuple[Optional[Any], Optional[Any]]:
    """Return the first (tool, comp) with the given ID, or (None, None)."""
    for tool, comp in find_tools_by_id(item, tool_id):
        return tool, comp
    return None, None


def get_tool_inputs(tool: Any, comp: Any, names: Iterable[str]) -> dict[str, Any]:
    """Read tool inputs at the comp's current time; skips None values."""
    time = comp.CurrentTime
    out = {}
    for name in names:
        val = tool.GetInput(name, time)
        if val is not None:
            out[name] = val
    return out


def set_tool_inputs(tool: Any, comp: Any, values: dict[str, Any]) -> None:
    """Set tool inputs at the comp's current time."""
    time = comp.CurrentTime
    for name, val in values.items():
        tool.SetInput(name, val, time)
