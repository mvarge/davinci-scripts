#!/usr/bin/env python3
"""Export beat-counter subtitles (SRT) from time-signature markers in DaVinci Resolve.

WHAT THIS IS FOR
----------------
Turning a metronome/click timeline into on-screen bar+beat counters, for songs in
shifting time signatures. You mark each bar with its time signature; this script
subdivides every bar into beats and writes SRT files you import onto subtitle
tracks. Subtitle tracks are the key trick: styling is set ONCE at track level
(Inspector > Track) and applies to every caption, so font/size/colour/spacing/
background box are a single edit rather than hundreds.

Subtitle tracks are used instead of Text+ titles because:
  - Track-level styling restyles all captions at once (manual PDF p. 1278).
  - No Fusion comp per caption, so the timeline stays responsive. Hundreds of
    Text+ clips do not.
  - "Save Track as Preset" reuses the exact look on the next song (p. 1280).
  - InsertFusionTitleIntoTimeline cannot choose its track anyway
    (SetCurrentTrackIndex passes hasattr but is not callable), whereas
    "Insert Selected Subtitles to Timeline Using Timecode" places by timecode.

PREREQUISITES
-------------
1. Resolve Studio running, project open, timeline open.
2. Preferences > General > External scripting using = Local.
3. Every bar has a marker whose NAME is that bar's time signature: "6/4", "5/8",
   "7/4", "4/4". One marker per bar, on the downbeat.
   The LAST marker only terminates the previous bar; it produces no captions.

LAYOUT MODES
------------
--layout two-line  (default)
    ONE file, ONE subtitle track, each caption two lines ("6/4" newline "3/4").
    Both lines share font and size; Line Spacing (Inspector > Track) pushes them
    apart. This is the default because it is the only layout that needs a single
    subtitle track -- see the ONE VISIBLE TRACK note below.

--layout beats-only
    ONE file, single line "3/4". Just the beat counter.

--layout two-track
    Writes TWO files: ST1 = one caption per bar holding the signature, ST2 = one
    caption per beat. NOT generally usable: only one subtitle track can be
    visible at a time (manual PDF p. 1268), so the two tracks cannot both be on
    screen. Kept for the Subtitle Regions route (below) and for exporting the
    bar map on its own.

ONE VISIBLE TRACK (the constraint that shapes all of this)
----------------------------------------------------------
Only one subtitle track is visible at any time -- enabling one DISABLES all
others (manual PDF p. 1268). So "put the signature on one track and the beats on
another" does not work, however tempting it looks.

The supported way to get two independently-styled lines on screen at once is
Subtitle Regions: up to three regions (R1/R2/R3) INSIDE a single track, each
with its own Captions list and style settings including font and text position
(p. 1283-1284). Right-click inside the track body (not the header) > Add
Subtitle Region, then drag captions between regions. There is no scripting API
for regions, and insert-by-timecode always lands in R1, so populating R2 is
manual dragging. Only worth it if the two lines must differ in size.

If both lines can share a size -- the common case -- use the default two-line
layout and space them with Line Spacing. Far less work.

BEAT SUBDIVISION
----------------
Beats divide the bar evenly by the numerator, using floor division with the
remainder pushed onto the LAST intervals -- identical to create_beat_markers.py,
so captions land exactly on markers that script produced. A 6/4 bar of 106
frames gives intervals [17,17,17,18,18,19] rather than drifting.

The denominator is carried into the beat label, so a 5/8 bar counts 1/8..5/8 and
a 6/4 bar counts 1/4..6/4. Musically correct, unlike labelling eighth-note bars
as "1/5".

Captions are gap-free and back-to-back: each beat's caption ends exactly where
the next begins, so the counter is on screen continuously.

TIMECODE
--------
SRT times are the timeline's ABSOLUTE timecode (marker frame + GetStartFrame),
which is what "Insert Selected Subtitles to Timeline Using Timecode" matches
against. Marker frames from GetMarkers() are timeline-RELATIVE; mixing the two
domains is the classic Resolve scripting bug (see RESOLVE_SCRIPTING_GUIDE.md).

IMPORTING (Resolve UI -- scripting has no subtitle-import API)
-------------------------------------------------------------
1. Media Pool > right-click empty space > Import Subtitle > select the .srt.
2. Right-click the imported clip > "Insert Selected Subtitles to Timeline Using
   Timecode". It decomposes into individual captions and creates the subtitle
   track automatically (manual PDF p. 1271).
3. Click the subtitle TRACK HEADER > Inspector > Track panel. Set font, size,
   colour, Position Y, Line Spacing, plus Drop Shadow / Stroke / Background.
   Applies to every caption on that track. Raise Line Spacing to separate the
   signature from the beat count.
4. Optional: option menu (3 dots) > Save Track as Preset to reuse next time.

USAGE
-----
    python3 export_beat_subtitles.py
    python3 export_beat_subtitles.py --layout beats-only
    python3 export_beat_subtitles.py --outdir ~/Desktop --prefix mysong
    python3 export_beat_subtitles.py --dry-run

Read-only with respect to Resolve: this script never writes to the timeline.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, NamedTuple

from resolve_kit.timecode import parse_fps

# Note written by create_beat_markers.py onto its generated sub-markers. Those
# are beat markers, not bar markers, so they must be excluded from the bar list.
GENERATED_MARKER_NOTE = "[beat-marker-script]"

_SIG_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


class Bar(NamedTuple):
    """One bar: start/end are timeline-RELATIVE marker frames; end is the next
    bar's start (exclusive)."""

    start: int
    end: int
    numerator: int
    denominator: int


class Caption(NamedTuple):
    """One subtitle. Frames are timeline-relative; convert at write time."""

    start: int
    end: int
    text: str


def parse_signature(name: str) -> tuple[int, int] | None:
    """Parse a marker name as "N/D". Returns None if it is not a signature.

    Rejects zero numerator/denominator: a 0-beat bar cannot be subdivided and a
    0 denominator is not a note value.
    """
    match = _SIG_RE.match(name or "")
    if not match:
        return None
    num, den = int(match.group(1)), int(match.group(2))
    if num <= 0 or den <= 0:
        return None
    return num, den


def collect_bars(markers: dict[int, dict]) -> list[Bar]:
    """Build the bar list from a GetMarkers() dict.

    Skips markers generated by create_beat_markers.py and any marker whose name
    is not a time signature, so unrelated notes/comments on the timeline are
    harmless. The final signature marker terminates the last bar and yields no
    bar of its own.
    """
    sigs: list[tuple[int, int, int]] = []
    for frame, data in markers.items():
        if (data.get("note") or "") == GENERATED_MARKER_NOTE:
            continue
        parsed = parse_signature(data.get("name", ""))
        if parsed is None:
            continue
        sigs.append((frame, parsed[0], parsed[1]))

    sigs.sort(key=lambda item: item[0])
    return [
        Bar(start=frame, end=sigs[i + 1][0], numerator=num, denominator=den)
        for i, (frame, num, den) in enumerate(sigs[:-1])
    ]


def beat_frames(bar: Bar) -> list[tuple[int, int]]:
    """Split a bar into (start, end) frame pairs, one per beat.

    Floor division with the remainder pushed onto the last intervals, matching
    create_beat_markers.py exactly. The final beat is snapped to bar.end so
    rounding can never leave a gap before the next bar.
    """
    total = bar.end - bar.start
    base, remainder = divmod(total, bar.numerator)
    cutoff = bar.numerator - remainder

    spans: list[tuple[int, int]] = []
    cursor = bar.start
    for beat in range(1, bar.numerator + 1):
        step = base if beat <= cutoff else base + 1
        end = bar.end if beat == bar.numerator else cursor + step
        spans.append((cursor, end))
        cursor = end
    return spans


def build_signature_captions(bars: list[Bar]) -> list[Caption]:
    """One caption per bar, spanning the whole bar. Used by --layout two-track."""
    return [Caption(b.start, b.end, f"{b.numerator}/{b.denominator}") for b in bars]


def build_beat_captions(bars: list[Bar], with_signature: bool = False) -> list[Caption]:
    """One caption per beat. Two lines (signature above beat) if with_signature."""
    captions: list[Caption] = []
    for bar in bars:
        sig = f"{bar.numerator}/{bar.denominator}"
        for index, (start, end) in enumerate(beat_frames(bar), start=1):
            beat = f"{index}/{bar.denominator}"
            captions.append(Caption(start, end, f"{sig}\n{beat}" if with_signature else beat))
    return captions


def srt_timestamp(absolute_frame: int, fps: float) -> str:
    """Format an ABSOLUTE frame as an SRT timestamp (HH:MM:SS,mmm).

    SRT is millisecond-based, so the sub-second frame is converted with the real
    fps (not the nominal timecode rate) to stay accurate on NTSC rates.
    """
    whole = int(fps)
    remaining = absolute_frame
    hours, remaining = divmod(remaining, 3600 * whole)
    minutes, remaining = divmod(remaining, 60 * whole)
    seconds, frames = divmod(remaining, whole)
    millis = int(round(frames * 1000.0 / fps))
    if millis > 999:  # rounding can spill on fractional rates
        millis, seconds = 0, seconds + 1
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(captions: list[Caption], fps: float, timeline_start: int) -> str:
    """Render captions as SRT text, rebasing relative frames to absolute."""
    blocks = [
        f"{i}\n"
        f"{srt_timestamp(timeline_start + c.start, fps)} --> "
        f"{srt_timestamp(timeline_start + c.end, fps)}\n"
        f"{c.text}\n"
        for i, c in enumerate(captions, start=1)
    ]
    return "\n".join(blocks)


def validate(captions: list[Caption]) -> list[str]:
    """Sanity-check captions. Returns a list of human-readable problems."""
    problems: list[str] = []
    for caption in captions:
        if caption.end <= caption.start:
            problems.append(f"non-positive duration at frame {caption.start}")
    for earlier, later in zip(captions, captions[1:]):
        if later.start < earlier.end:
            problems.append(f"overlap at frame {later.start}")
        elif later.start > earlier.end:
            problems.append(f"gap before frame {later.start}")
    return problems


def summarize(bars: list[Bar], fps: float) -> str:
    """Human-readable tempo/meter summary, for confirming the read was correct."""
    if not bars:
        return "no bars"
    counts: dict[str, int] = {}
    bpms: list[float] = []
    for bar in bars:
        sig = f"{bar.numerator}/{bar.denominator}"
        counts[sig] = counts.get(sig, 0) + 1
        seconds = (bar.end - bar.start) / fps
        if seconds > 0:
            quarters = bar.numerator * (4.0 / bar.denominator)
            bpms.append(quarters / seconds * 60)
    meters = ", ".join(f"{sig} x{n}" for sig, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    tempo = f"{sum(bpms) / len(bpms):.1f} BPM (range {min(bpms):.1f}-{max(bpms):.1f})" if bpms else "?"
    return f"{len(bars)} bars | {meters} | ~{tempo}"


def write_file(path: str, text: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [DRY RUN] would write {path}")
        return
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"  wrote {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export beat-counter SRT subtitles from time-signature markers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--layout",
        choices=("two-line", "beats-only", "two-track"),
        default="two-line",
        help="two-line: one file/one track, signature above beat (default). "
        "beats-only: beat counter only. two-track: separate signature + beat "
        "files -- only usable via Subtitle Regions, since just one subtitle "
        "track can be visible at a time.",
    )
    parser.add_argument("--outdir", default=os.path.expanduser("~/Desktop"),
                        help="Output directory (default: ~/Desktop)")
    parser.add_argument("--prefix", default=None,
                        help="Filename prefix (default: sanitized timeline name)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be written without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from resolve_kit.connection import connect

    rk = connect()
    timeline = rk.timeline
    fps = parse_fps(timeline.GetSetting("timelineFrameRate"))
    start = timeline.GetStartFrame()

    print(f"Project:  {rk.project.GetName()}")
    print(f"Timeline: {timeline.GetName()} @ {fps} fps (start frame {start})")

    markers = timeline.GetMarkers() or {}
    bars = collect_bars(markers)
    if not bars:
        print(
            "\nERROR: no time-signature markers found.\n"
            "Name each bar's marker with its signature, e.g. '6/4', '5/8'.\n"
            "Remember the last marker only terminates the previous bar.",
            file=sys.stderr,
        )
        return 1

    print(f"Markers:  {len(markers)} total -> {summarize(bars, fps)}\n")

    prefix = args.prefix or re.sub(r"[^\w.-]+", "_", timeline.GetName()).strip("_") or "timeline"
    outdir = os.path.expanduser(args.outdir)
    if not args.dry_run:
        os.makedirs(outdir, exist_ok=True)

    if args.layout == "two-track":
        print(
            "NOTE: only one subtitle track can be visible at a time (manual\n"
            "      p. 1268), so these two files cannot both show on screen as\n"
            "      separate tracks. Use Subtitle Regions within one track, or\n"
            "      switch to --layout two-line.\n"
        )
        outputs = [
            (f"{prefix}_ST1_signature.srt", build_signature_captions(bars)),
            (f"{prefix}_ST2_beats.srt", build_beat_captions(bars)),
        ]
    elif args.layout == "two-line":
        outputs = [(f"{prefix}_beats_2line.srt", build_beat_captions(bars, with_signature=True))]
    else:
        outputs = [(f"{prefix}_beats.srt", build_beat_captions(bars))]

    failed = False
    for filename, captions in outputs:
        problems = validate(captions)
        status = "OK" if not problems else f"{len(problems)} PROBLEM(S)"
        print(f"{filename}: {len(captions)} captions [{status}]")
        for problem in problems[:5]:
            print(f"  ! {problem}")
            failed = True
        write_file(os.path.join(outdir, filename), render_srt(captions, fps, start), args.dry_run)

    print(
        "\nImport: Media Pool > right-click > Import Subtitle, then right-click the\n"
        "clip > 'Insert Selected Subtitles to Timeline Using Timecode'.\n"
        "Style once via the subtitle TRACK HEADER > Inspector > Track panel;\n"
        "raise Line Spacing to separate the signature from the beat count."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
