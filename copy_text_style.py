#!/usr/bin/env python3
"""
Text+ Style Copier for DaVinci Resolve

Copies shading, outline, shadow, font, and layout properties from the FIRST
Text+ item on the timeline to ALL other Text+ items. Each item keeps its own
text content (StyledText) — only the visual style is copied.

Workflow:
  1. Style the FIRST Text+ item in your timeline exactly how you want it
     (font, size, color, outline, shadow, shading elements, etc.)
  2. Run this script. It reads the style from that first Text+ and applies
     it to every other Text+ item on the timeline.
  3. If it doesn't look right, Cmd+Z in Resolve to undo.

What gets copied:
  - Font, style (bold/italic), and size
  - Line spacing, character spacing, justification
  - All 8 shading elements (fill, outline, shadow, border, etc.)
    including colors, opacity, thickness, softness, offsets
  - Anti-aliasing settings

What is NOT copied (preserved per item):
  - StyledText (the actual text content)
  - Position on timeline (start frame, duration)

Notes:
  - The script finds Text+ items across ALL video tracks.
  - The first Text+ found (by track order, then position) is the source.
  - Resolve must be running with a project and timeline open.
  - External scripting must be set to "Local" in Preferences → General.

Usage:
  python3 copy_text_style.py [--dry-run]

  --dry-run   Show what would be done without making changes
"""

import sys
import argparse

sys.path.append(
    "/Library/Application Support/Blackmagic Design"
    "/DaVinci Resolve/Developer/Scripting/Modules"
)
import DaVinciResolveScript as dvr


# All style properties to copy from the source Text+ to targets.
# Covers shading elements 1-8, font settings, layout, and rendering.
# StyledText is intentionally excluded to preserve each item's content.
STYLE_PROPERTIES = []

# Shading element properties (elements 1 through 8)
for n in range(1, 9):
    STYLE_PROPERTIES.extend([
        f"Enabled{n}",
        f"Properties{n}", f"Opacity{n}", f"Overlap{n}",
        f"ElementShape{n}",
        f"Thickness{n}", f"JoinStyle{n}", f"MiterLimit{n}",
        f"Level{n}",
        f"Red{n}", f"Green{n}", f"Blue{n}", f"Alpha{n}",
        f"ImageShadingSampling{n}", f"ImageShadingEdges{n}",
        f"ShadingMapping{n}", f"ShadingMappingSize{n}",
        f"ShadingMappingAspect{n}", f"ShadingMappingLevel{n}",
        f"Softness{n}", f"SoftnessX{n}", f"SoftnessY{n}",
        f"SoftnessBlend{n}",
        f"Position{n}", f"PriorityBack{n}",
        f"Offset{n}", f"Pivot{n}",
        f"SizeX{n}", f"SizeY{n}",
    ])

# Font and text layout
STYLE_PROPERTIES.extend([
    "Font", "Style", "Size",
    "LineSpacing", "LineSpacingClone",
    "CharacterSpacing", "CharacterSpacingClone",
    "WordSpacing",
    "VerticalJustification", "VerticalJustificationNew",
    "HorizontalJustificationNew",
    "AntiAliasing",
    # Color clones (main fill color shown in text tab)
    "Red1Clone", "Green1Clone", "Blue1Clone", "Alpha1Clone",
])


def connect_to_resolve():
    """Connect to the running DaVinci Resolve instance."""
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("ERROR: Could not connect to DaVinci Resolve.")
        print("  - Is Resolve running?")
        print("  - Preferences → General → External scripting using → Local")
        sys.exit(1)

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("ERROR: No project is currently open.")
        sys.exit(1)

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("ERROR: No timeline is currently open.")
        sys.exit(1)

    return resolve, project, timeline


def find_text_plus_items(timeline):
    """Find all Text+ items across all video tracks."""
    text_items = []
    track_count = timeline.GetTrackCount("video")
    for t in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("video", t)
        if not items:
            continue
        for item in items:
            if item.GetName() == "Text+" and item.GetFusionCompCount() > 0:
                text_items.append((t, item))
    return text_items


def get_textplus_tool(item):
    """Get the TextPlus tool from a timeline item's Fusion comp."""
    comp = item.GetFusionCompByIndex(1)
    if not comp:
        return None, None
    tools = comp.GetToolList()
    for idx, tool in tools.items():
        if tool.ID == "TextPlus":
            return tool, comp
    return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Copy Text+ style from the first item to all others"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    resolve, project, timeline = connect_to_resolve()

    print(f"Project: {project.GetName()}")
    print(f"Timeline: {timeline.GetName()}")
    print()

    # Find all Text+ items
    text_items = find_text_plus_items(timeline)

    if len(text_items) == 0:
        print("No Text+ items found on the timeline!")
        sys.exit(0)

    if len(text_items) == 1:
        print("Only 1 Text+ item found — need at least 2 (1 source + targets).")
        sys.exit(0)

    print(f"Found {len(text_items)} Text+ items")

    # Source is the first one
    source_track, source_item = text_items[0]
    source_tool, source_comp = get_textplus_tool(source_item)
    if not source_tool:
        print("ERROR: Could not access TextPlus tool in the first item.")
        sys.exit(1)

    source_text = source_tool.GetInput("StyledText", source_comp.CurrentTime)
    print(f"Source: Track {source_track}, start={source_item.GetStart()}")
    print(f"  Text: \"{source_text[:50]}{'...' if len(str(source_text)) > 50 else ''}\"")
    print()

    # Read all style properties from source
    source_values = {}
    for prop in STYLE_PROPERTIES:
        val = source_tool.GetInput(prop, source_comp.CurrentTime)
        if val is not None:
            source_values[prop] = val

    print(f"Read {len(source_values)} style properties from source")
    print()

    if args.dry_run:
        print(f"[DRY RUN] Would apply style to {len(text_items) - 1} Text+ items")
        for i, (track, item) in enumerate(text_items[1:], 2):
            tool, comp = get_textplus_tool(item)
            if tool and comp:
                text = tool.GetInput("StyledText", comp.CurrentTime)
                print(f"  [{i}] Track {track}, start={item.GetStart()}: \"{str(text)[:30]}...\"")
        sys.exit(0)

    # Apply to all other items
    applied = 0
    failed = 0
    for i, (track, item) in enumerate(text_items[1:], 2):
        tool, comp = get_textplus_tool(item)
        if not tool or not comp:
            print(f"  [{i}] Track {track}, start={item.GetStart()}: SKIPPED (no TextPlus tool)")
            failed += 1
            continue

        for prop, val in source_values.items():
            tool.SetInput(prop, val, comp.CurrentTime)

        applied += 1

    print(f"Done! Applied style to {applied} Text+ items.")
    if failed > 0:
        print(f"  ({failed} items skipped due to errors)")
    print(f"\nIf it doesn't look right, Cmd+Z in Resolve to undo.")


if __name__ == "__main__":
    main()
