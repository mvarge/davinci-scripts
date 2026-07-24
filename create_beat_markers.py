#!/usr/bin/env python3
"""
Beat Sub-Marker Creator for DaVinci Resolve

Workflow:
  1. In DaVinci Resolve, add markers on the timeline at the start of each musical section.
     Set each marker's NAME to the beat count, optionally as a time signature like "6/4", "10/8".
     The script uses only the numerator (number of beats), ignoring the denominator.
  2. Run this script. It reads those markers, and between each consecutive pair,
     it creates evenly-spaced sub-markers representing each beat.

Example:
  Marker A at frame 0    (name="6")  →  next marker B at frame 120
  Marker B at frame 120  (name="4")  →  next marker C at frame 127

  Between A and B: 6 beats across 120 frames (divides evenly at 20 each)
    → sub-markers at frames 20, 40, 60, 80, 100

  Between B and C: 4 beats across 7 frames (7 ÷ 4 = 1 remainder 3)
    → intervals: [1, 2, 2, 2] — early beats stay tight, slack pushed to end
    → sub-markers at frames 121, 123, 125

Notes:
  - The first beat of each section is the existing marker itself, so we only add (N-1) sub-markers.
  - Sub-markers are added with a distinct color ("Blue" by default) to distinguish them
    from the original section markers.
  - The last marker in the timeline is ignored (no next marker to measure to).
  - Resolve must be running with a project and timeline open.
  - External scripting must be set to "Local" in Preferences → General.

Usage:
  python3 create_beat_markers.py [--color Blue] [--dry-run]

  --color COLOR    Color for the generated beat sub-markers (default: Blue)
                   Available: Red, Orange, Yellow, Lime, Cyan, Blue, Purple, Pink, etc.
  --dry-run        Print what would be done without actually adding markers
  --clear          Clear all previously generated beat markers before creating new ones
"""

import sys
import argparse

sys.path.append(
    "/Library/Application Support/Blackmagic Design"
    "/DaVinci Resolve/Developer/Scripting/Modules"
)
import DaVinciResolveScript as dvr


# Marker color used for generated beat sub-markers (to distinguish from user markers)
DEFAULT_SUB_MARKER_COLOR = "Cyan"
# Prefix used in the note field to identify script-generated markers
GENERATED_MARKER_NOTE = "[beat-marker-script]"


def connect_to_resolve():
    """Connect to the running DaVinci Resolve instance and return (resolve, project, timeline)."""
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        print("ERROR: Could not connect to DaVinci Resolve.")
        print("  - Is Resolve running?")
        print("  - Preferences → General → External scripting using → Local")
        sys.exit(1)

    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("ERROR: No project is currently open in DaVinci Resolve.")
        sys.exit(1)

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        print("ERROR: No timeline is currently open in DaVinci Resolve.")
        sys.exit(1)

    return resolve, project, timeline


def get_section_markers(timeline):
    """
    Get all markers from the timeline and return only the 'section' markers
    (those whose name is a number representing beat count).

    Returns a sorted list of (frame, beat_count, marker_data) tuples.
    """
    all_markers = timeline.GetMarkers()
    if not all_markers:
        return []

    section_markers = []
    for frame, data in all_markers.items():
        name = data.get("name", "").strip()
        # Skip script-generated markers
        if data.get("note", "") == GENERATED_MARKER_NOTE:
            continue
        # Parse beat count: supports "6", "6/4", "10/8" etc. (uses numerator only)
        try:
            numerator = name.split("/")[0].strip()
            beat_count = int(numerator)
            if beat_count > 0:
                section_markers.append((frame, beat_count, data))
        except (ValueError, IndexError):
            # Not a beat marker, skip it
            continue

    # Sort by frame position
    section_markers.sort(key=lambda x: x[0])
    return section_markers


def clear_generated_markers(timeline):
    """Remove all previously generated beat sub-markers (identified by note field)."""
    all_markers = timeline.GetMarkers()
    if not all_markers:
        return 0

    count = 0
    for frame, data in list(all_markers.items()):
        if data.get("note", "") == GENERATED_MARKER_NOTE:
            timeline.DeleteMarkerAtFrame(frame)
            count += 1

    return count


def calculate_beat_positions(start_frame, end_frame, beat_count):
    """
    Calculate frame positions for sub-beats between start_frame and end_frame.

    The start_frame IS beat 1, so we create (beat_count - 1) sub-markers
    between start_frame and end_frame.

    Frame distribution: keeps early beats tight and uniform (floor division),
    with any remainder frames pushed to the LAST intervals. This makes the
    beat feel consistent at the start and any slack accumulates at the end
    (just before the next section marker).

    Example: 6 beats across 20 frames → intervals [3, 3, 3, 3, 4, 4]
      Beat 1 at +0, Beat 2 at +3, Beat 3 at +6, Beat 4 at +9,
      Beat 5 at +12, Beat 6 at +16, next marker at +20

    Example: 4 beats across 7 frames → intervals [1, 1, 2, 3]
      → actually [1, 1, 2, 3] no — let's think:
      7 // 4 = 1, remainder 3. 4 intervals total.
      First (4 - 3) = 1 intervals get base (1), last 3 get base+1 (2).
      → intervals [1, 2, 2, 2]
      Beat 1 at +0, Beat 2 at +1, Beat 3 at +3, Beat 4 at +5, next marker at +7

    Returns a list of frame positions (integers) for beats 2 through beat_count.
    """
    if beat_count <= 1:
        return []

    total_frames = end_frame - start_frame
    base_interval = total_frames // beat_count
    remainder = total_frames % beat_count

    # There are `beat_count` intervals (including the one after the last beat
    # to the next section marker). We want the LAST `remainder` intervals to
    # be (base + 1) and the first (beat_count - remainder) to be `base`.
    # This keeps early beats tight and pushes slack to the end.
    cutoff = beat_count - remainder  # intervals 1..cutoff get `base`, rest get `base+1`

    positions = []
    current = start_frame
    for i in range(1, beat_count):
        if i <= cutoff:
            current += base_interval
        else:
            current += base_interval + 1
        if current < end_frame:
            positions.append(current)

    return positions


def main():
    parser = argparse.ArgumentParser(
        description="Create beat sub-markers between section markers in DaVinci Resolve"
    )
    parser.add_argument(
        "--color",
        default=DEFAULT_SUB_MARKER_COLOR,
        help=f"Color for generated beat sub-markers (default: {DEFAULT_SUB_MARKER_COLOR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without actually adding markers",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all previously generated beat markers before creating new ones",
    )
    args = parser.parse_args()

    # Connect to Resolve
    resolve, project, timeline = connect_to_resolve()

    timeline_name = timeline.GetName()
    fps = timeline.GetSetting("timelineFrameRate")
    print(f"Project: {project.GetName()}")
    print(f"Timeline: {timeline_name}")
    print(f"Frame Rate: {fps} fps")
    print()

    # Clear old generated markers if requested
    if args.clear:
        cleared = clear_generated_markers(timeline)
        print(f"Cleared {cleared} previously generated beat markers.")
        print()

    # Get section markers
    section_markers = get_section_markers(timeline)

    if len(section_markers) == 0:
        print("No section markers found!")
        print("Add markers to the timeline with their NAME set to the beat count (e.g., '6/4', '10/8', or just '4').")
        sys.exit(0)

    if len(section_markers) == 1:
        print(f"Only 1 section marker found at frame {section_markers[0][0]} with {section_markers[0][1]} beats.")
        print("Need at least 2 section markers to create beat sub-markers.")
        sys.exit(0)

    print(f"Found {len(section_markers)} section markers:")
    for i, (frame, beats, data) in enumerate(section_markers):
        color = data.get("color", "?")
        print(f"  [{i+1}] Frame {frame} — {beats} beats ({color})")
    print()

    # Process each consecutive pair
    total_added = 0
    for i in range(len(section_markers) - 1):
        start_frame, beat_count, start_data = section_markers[i]
        end_frame, _, _ = section_markers[i + 1]

        positions = calculate_beat_positions(start_frame, end_frame, beat_count)

        total_frames = end_frame - start_frame
        try:
            fps_float = float(fps)
            duration_sec = total_frames / fps_float
            bpm_estimate = (beat_count / duration_sec) * 60
            bpm_str = f" (~{bpm_estimate:.1f} BPM)"
        except (ValueError, ZeroDivisionError):
            bpm_str = ""

        print(
            f"Section {i+1}: frame {start_frame} → {end_frame} "
            f"({total_frames} frames, {beat_count} beats{bpm_str})"
        )

        for j, frame_pos in enumerate(positions):
            beat_num = j + 2  # beat 1 is the section marker itself
            marker_name = f"{beat_num}/{beat_count}"

            if args.dry_run:
                print(f"  [DRY RUN] Would add marker at frame {frame_pos}: beat {marker_name}")
                total_added += 1
            else:
                success = timeline.AddMarker(
                    frame_pos,
                    args.color,
                    marker_name,
                    GENERATED_MARKER_NOTE,
                    1,
                    "",
                )
                if success:
                    total_added += 1
                else:
                    print(f"  WARNING: Failed to add marker at frame {frame_pos} (beat {marker_name})")
                    print(f"           There may already be a marker at this frame.")

        print(f"  → Added {len(positions)} sub-markers")

    print()
    if args.dry_run:
        print(f"DRY RUN complete. Would have added {total_added} beat sub-markers total.")
    else:
        print(f"Done! Added {total_added} beat sub-markers total.")
        print(f"Sub-markers are colored '{args.color}' with note '{GENERATED_MARKER_NOTE}'.")
        print(f"Run with --clear to remove them later.")


if __name__ == "__main__":
    main()
