"""Fake Resolve API objects for unit-testing resolve_kit without Resolve.

The fakes mimic the scripting bridge's actual behavior, including its traps:
- FakeBridgeObject fabricates a callable for ANY attribute (hasattr lies),
  mirroring fusionscript's proxy behavior.
- FakeTimeline stores markers keyed by whatever frame you pass (no
  validation), like the real GetMarkers/AddMarker round-trip.
"""

from __future__ import annotations

import pytest


class FakeBridgeObject:
    """Base fake reproducing the bridge's attribute fabrication: any unknown
    attribute resolves to a callable returning None, so hasattr is always
    True — exactly like fusionscript proxies."""

    def __getattr__(self, name):
        # Only called when the attribute is NOT found normally.
        return lambda *args, **kwargs: None


class FakeTimeline(FakeBridgeObject):
    def __init__(self, name="Timeline 1", start_frame=90000, end_frame=94018,
                 fps_setting="25", video_tracks=2, audio_tracks=2):
        self._name = name
        self._start = start_frame
        self._end = end_frame
        self._fps_setting = fps_setting
        self._markers: dict[int, dict] = {}
        self._tracks = {"video": video_tracks, "audio": audio_tracks}
        self._items: dict[tuple[str, int], list] = {}
        self._timecode = "01:00:00:00"

    def GetName(self):
        return self._name

    def GetStartFrame(self):
        return self._start

    def GetEndFrame(self):
        return self._end

    def GetSetting(self, key):
        if key == "timelineFrameRate":
            return self._fps_setting
        return ""

    def GetTrackCount(self, kind):
        return self._tracks.get(kind, 0)

    def GetItemListInTrack(self, kind, index):
        return self._items.get((kind, index), [])

    def GetCurrentTimecode(self):
        return self._timecode

    def SetCurrentTimecode(self, tc):
        self._timecode = tc
        return True

    # Markers: accepts any frame without validation (the real trap).
    def GetMarkers(self):
        return dict(self._markers)

    def AddMarker(self, frame, color, name, note, duration, custom_data):
        if frame in self._markers:
            return False
        self._markers[frame] = {
            "color": color, "name": name, "note": note,
            "duration": duration, "customData": custom_data,
        }
        return True

    def DeleteMarkerAtFrame(self, frame):
        return self._markers.pop(frame, None) is not None


class FakeProject(FakeBridgeObject):
    def __init__(self, name="Fake Project", timelines=None):
        self._name = name
        self._timelines = timelines if timelines is not None else [FakeTimeline()]
        self._current = self._timelines[0] if self._timelines else None
        self._media_pool = FakeBridgeObject()

    def GetName(self):
        return self._name

    def GetCurrentTimeline(self):
        return self._current

    def SetCurrentTimeline(self, tl):
        if tl in self._timelines:
            self._current = tl
            return True
        return False

    def GetTimelineCount(self):
        return len(self._timelines)

    def GetTimelineByIndex(self, i):
        if 1 <= i <= len(self._timelines):
            return self._timelines[i - 1]
        return None

    def GetMediaPool(self):
        return self._media_pool


class FakeProjectManager(FakeBridgeObject):
    def __init__(self, project=None):
        self._project = project if project is not None else FakeProject()

    def GetCurrentProject(self):
        return self._project


class FakeResolve(FakeBridgeObject):
    def __init__(self, project_manager=None, alive=True):
        self._pm = project_manager if project_manager is not None else FakeProjectManager()
        self._alive = alive
        self._page = "edit"

    def GetProjectManager(self):
        return self._pm

    def GetVersion(self):
        if not self._alive:
            raise RuntimeError("connection lost")
        return [21, 0, 3, 7, ""]

    def GetProductName(self):
        return "DaVinci Resolve Studio"

    def GetVersionString(self):
        return "21.0.3.7"

    def GetCurrentPage(self):
        return self._page

    def OpenPage(self, page):
        self._page = page
        return True


class FakeTool(FakeBridgeObject):
    ID = "TextPlus"

    def __init__(self, inputs=None, sticky=None):
        # sticky: input names whose writes are silently dropped
        # (mimics setters that return without effect).
        self._inputs = dict(inputs or {})
        self._sticky = set(sticky or [])

    def GetInput(self, name, time=None):
        return self._inputs.get(name)

    def SetInput(self, name, value, time=None):
        if name not in self._sticky:
            self._inputs[name] = value


class FakeComp(FakeBridgeObject):
    CurrentTime = 0

    def __init__(self, tools=None):
        self._tools = tools or {}

    def GetToolList(self):
        return dict(self._tools)


class FakeTimelineItem(FakeBridgeObject):
    def __init__(self, name="Text+", comps=None, start=0):
        self._name = name
        self._comps = comps or []
        self._start = start

    def GetName(self):
        return self._name

    def GetStart(self):
        return self._start

    def GetFusionCompCount(self):
        return len(self._comps)

    def GetFusionCompByIndex(self, i):
        if 1 <= i <= len(self._comps):
            return self._comps[i - 1]
        return None


@pytest.fixture
def timeline():
    return FakeTimeline()


@pytest.fixture
def resolve():
    return FakeResolve()


@pytest.fixture
def rk(resolve):
    from resolve_kit.connection import ResolveKit

    return ResolveKit(resolve=resolve)
