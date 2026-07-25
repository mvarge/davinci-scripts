"""Unit tests for resolve_kit.connection (ResolveKit) against fakes."""

import pytest

from resolve_kit.connection import ResolveConnectionError, ResolveKit
from tests.conftest import (
    FakeProject,
    FakeProjectManager,
    FakeResolve,
    FakeTimeline,
)


class TestLiveness:
    def test_alive(self, rk):
        assert rk.is_alive()

    def test_dead_handle(self):
        rk = ResolveKit(resolve=FakeResolve(alive=False))
        assert not rk.is_alive()

    def test_version(self, rk):
        v = rk.version()
        assert v["product"] == "DaVinci Resolve Studio"
        assert v["version"] == "21.0.3.7"


class TestAccessors:
    def test_project(self, rk):
        assert rk.project.GetName() == "Fake Project"

    def test_no_project_raises(self):
        pm = FakeProjectManager(project=None)
        pm._project = None
        rk = ResolveKit(resolve=FakeResolve(project_manager=pm))
        with pytest.raises(ResolveConnectionError, match="No project"):
            _ = rk.project

    def test_no_timeline_raises(self):
        proj = FakeProject(timelines=[])
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        with pytest.raises(ResolveConnectionError, match="No timeline"):
            _ = rk.timeline

    def test_fps_parses_string(self, rk):
        assert rk.fps == 25.0

    def test_fps_ntsc_string(self):
        proj = FakeProject(timelines=[FakeTimeline(fps_setting="23.976")])
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        assert rk.fps == 23.976

    def test_fps_garbage_raises_connection_error(self):
        proj = FakeProject(timelines=[FakeTimeline(fps_setting="garbage")])
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        with pytest.raises(ResolveConnectionError):
            _ = rk.fps

    def test_page(self, rk):
        assert rk.page() == "edit"


class TestFindTimeline:
    def test_found(self):
        tls = [FakeTimeline(name="A"), FakeTimeline(name="B")]
        proj = FakeProject(timelines=tls)
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        assert rk.find_timeline("B") is tls[1]

    def test_not_found(self, rk):
        assert rk.find_timeline("nope") is None


class TestIterators:
    def test_iter_video_items(self):
        tl = FakeTimeline(video_tracks=2)
        tl._items[("video", 1)] = ["a", "b"]
        tl._items[("video", 2)] = ["c"]
        proj = FakeProject(timelines=[tl])
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        items = list(rk.iter_video_items())
        assert items == [(1, "a"), (1, "b"), (2, "c")]

    def test_iter_handles_none_track_list(self):
        tl = FakeTimeline(video_tracks=1)
        tl._items[("video", 1)] = None  # API returns None for empty tracks
        proj = FakeProject(timelines=[tl])
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        assert list(rk.iter_video_items()) == []


class TestSaveRestoreState:
    def test_roundtrip(self, rk, resolve):
        state = rk.save_state()
        assert state["page"] == "edit"
        assert state["timeline"] == "Timeline 1"
        assert state["timecode"] == "01:00:00:00"

        resolve.OpenPage("color")
        rk.timeline.SetCurrentTimecode("01:00:10:00")

        rk.restore_state(state)
        assert rk.page() == "edit"
        assert rk.timeline.GetCurrentTimecode() == "01:00:00:00"

    def test_restore_switches_timeline(self):
        tls = [FakeTimeline(name="A"), FakeTimeline(name="B")]
        proj = FakeProject(timelines=tls)
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        state = rk.save_state()
        proj.SetCurrentTimeline(tls[1])
        rk.restore_state(state)
        assert rk.timeline.GetName() == "A"


class TestSummary:
    def test_full(self, rk):
        s = rk.summary()
        assert s["project"] == "Fake Project"
        assert s["fps"] == 25.0
        assert s["product"] == "DaVinci Resolve Studio"
        assert s["markers"] == 0
        assert s["start_frame"] == 90000

    def test_fps_none_on_garbage(self):
        proj = FakeProject(timelines=[FakeTimeline(fps_setting="???")])
        rk = ResolveKit(resolve=FakeResolve(FakeProjectManager(proj)))
        assert rk.summary()["fps"] is None
