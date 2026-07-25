#!/usr/bin/env python3
"""Live smoke test for resolve_kit — requires Resolve Studio running.

Default mode is NON-INVASIVE: runs against the currently open project and
timeline, using only reversible operations (markers tagged with custom_data,
page switches wrapped in save/restore). Verifications read RAW Resolve state,
not resolve_kit's own wrappers, so wrapper bugs can't hide.

--full additionally creates a disposable project (prefix `_rk_test_`) with a
synthetic clip, exercises timeline creation, then deletes it and reopens your
original project. This switches the current project — only use it when
nothing unsaved is at stake.

Usage:
    PYTHONPATH=. python3 tests/live_smoke.py [--full]
"""

from __future__ import annotations

import argparse
import sys
import time

from resolve_kit import (
    add_marker,
    connect,
    delete_markers,
    get_markers,
    has_method,
    verify_by_readback,
)

TAG = "rk-live-smoke"
PROJECT_PREFIX = "_rk_test_"

_passed = 0
_failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if ok:
        _passed += 1
    else:
        _failed += 1


def test_connection(rk) -> None:
    print("connection:")
    check("is_alive", rk.is_alive())
    v = rk.version()
    check("version populated", bool(v.get("product") and v.get("version")))
    check("summary has project", bool(rk.summary().get("project")))
    check("has_method real", has_method(rk.timeline, "GetMarkers"))
    check("has_method fabricated", not has_method(rk.timeline, "TotallyMadeUp"))


def test_markers(rk) -> None:
    print("markers (reversible, custom_data-tagged):")
    tl = rk.timeline
    frame = 5

    # ensure a clean slate at our test frame
    raw_before = dict(tl.GetMarkers() or {})
    if frame in raw_before:
        print(f"  [SKIP] frame {frame} already has a user marker; using 7")
        frame = 7

    result = verify_by_readback(
        mutate=lambda: add_marker(tl, frame, color="lemon", name="smoke",
                                  custom_data=TAG),
        observe=lambda: (tl.GetMarkers() or {}).get(frame),  # RAW readback
        compare=lambda m: m is not None and m.get("customData") == TAG,
    )
    check("add + raw readback", result.ok)
    check("no contradiction", not result.contradiction)

    found = get_markers(tl, custom_data=TAG)
    check("filter by custom_data", frame in found)

    would = delete_markers(tl, custom_data=TAG, dry_run=True)
    check("dry_run previews", frame in would)
    check("dry_run does not delete", frame in (tl.GetMarkers() or {}))

    try:
        delete_markers(tl)
        check("no-filter guard", False, "ValueError not raised")
    except ValueError:
        check("no-filter guard", True)

    deleted = delete_markers(tl, custom_data=TAG)
    check("delete", frame in deleted)
    check("raw state clean after delete", frame not in (tl.GetMarkers() or {}))


def test_state_roundtrip(rk) -> None:
    print("save/restore state:")
    state = rk.save_state()
    try:
        rk.resolve.OpenPage("color")
        check("page switched", rk.page() == "color")
    finally:
        rk.restore_state(state)
    check("page restored", rk.page() == state["page"])
    if state.get("timecode"):
        check("playhead restored",
              rk.timeline.GetCurrentTimecode() == state["timecode"])


def test_disposable_project(rk) -> None:
    print("disposable project (--full):")
    pm = rk.project_manager
    original = rk.project.GetName()
    name = f"{PROJECT_PREFIX}{int(time.time())}"

    proj = pm.CreateProject(name)
    check("create project", proj is not None)
    if proj is None:
        return
    try:
        mp = proj.GetMediaPool()
        tl = mp.CreateEmptyTimeline("smoke_tl")
        check("create timeline", tl is not None)
        if tl is not None:
            check("timeline listed", proj.GetTimelineCount() == 1)
    finally:
        pm.CloseProject(proj)
        # DeleteProject is flaky on the current/recent project: retry.
        deleted = False
        for _ in range(3):
            if pm.DeleteProject(name):
                deleted = True
                break
            time.sleep(0.5)
        check("delete project (with retry)", deleted)
        check("original project reopened", bool(pm.LoadProject(original)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true",
                        help="also run disposable-project tests (switches projects)")
    args = parser.parse_args()

    rk = connect()
    info = rk.summary()
    print(f"target: {info['product']} {info['version']} — "
          f"project '{info['project']}'\n")

    test_connection(rk)
    test_markers(rk)
    test_state_roundtrip(rk)
    if args.full:
        test_disposable_project(rk)

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
