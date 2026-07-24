"""Connection helpers: locate the Resolve scripting module and connect."""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

# Default module locations per platform, per Blackmagic's scripting README.
_DEFAULT_MODULE_PATHS = {
    "darwin": [
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    ],
    "win32": [
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules",
    ],
    "linux": [
        "/opt/resolve/Developer/Scripting/Modules",
        "/home/resolve/Developer/Scripting/Modules",
    ],
}


class ResolveConnectionError(RuntimeError):
    """Raised when we cannot import the scripting module or reach Resolve."""


def load_resolve_module():
    """Import and return DaVinciResolveScript, extending sys.path if needed.

    Honors RESOLVE_SCRIPT_API env var (set by some installs) before falling
    back to the platform default paths.
    """
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError:
        pass

    candidates = []
    env_api = os.environ.get("RESOLVE_SCRIPT_API")
    if env_api:
        candidates.append(os.path.join(env_api, "Modules"))
    candidates.extend(_DEFAULT_MODULE_PATHS.get(sys.platform, []))

    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)

    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError as exc:
        raise ResolveConnectionError(
            "Could not import DaVinciResolveScript. Is DaVinci Resolve installed?\n"
            f"Searched: {candidates}\n"
            "You can also set RESOLVE_SCRIPT_API to your Scripting directory."
        ) from exc


@dataclass
class ResolveKit:
    """A connected Resolve session with convenience accessors.

    Attributes resolve/project_manager are always set; project/timeline are
    resolved lazily via properties so long-running scripts always see the
    *current* project/timeline.
    """

    resolve: Any
    project_manager: Any = field(default=None)

    def __post_init__(self):
        if self.project_manager is None:
            self.project_manager = self.resolve.GetProjectManager()

    # -- current state ------------------------------------------------------

    @property
    def project(self) -> Any:
        proj = self.project_manager.GetCurrentProject()
        if proj is None:
            raise ResolveConnectionError("No project is currently open in Resolve.")
        return proj

    @property
    def timeline(self) -> Any:
        tl = self.project.GetCurrentTimeline()
        if tl is None:
            raise ResolveConnectionError("No timeline is currently open in Resolve.")
        return tl

    @property
    def media_pool(self) -> Any:
        return self.project.GetMediaPool()

    @property
    def fps(self) -> float:
        """Timeline frame rate. GetSetting returns a string that is
        occasionally malformed; parse defensively."""
        from .timecode import parse_fps

        try:
            raw = self.timeline.GetSetting("timelineFrameRate")
        except Exception as exc:  # bridge errors surface as generic exceptions
            raise ResolveConnectionError(f"Could not read timeline frame rate: {exc}") from exc
        try:
            return parse_fps(raw)
        except ValueError as exc:
            raise ResolveConnectionError(str(exc)) from exc

    def page(self) -> str:
        """Current Resolve page (media, cut, edit, fusion, color, fairlight, deliver)."""
        return self.resolve.GetCurrentPage()

    # -- iteration helpers ---------------------------------------------------

    def iter_video_items(self, timeline: Any = None) -> Iterator[tuple[int, Any]]:
        """Yield (track_index, item) for every clip on every video track."""
        tl = timeline or self.timeline
        for track in range(1, tl.GetTrackCount("video") + 1):
            for item in tl.GetItemListInTrack("video", track) or []:
                yield track, item

    def iter_audio_items(self, timeline: Any = None) -> Iterator[tuple[int, Any]]:
        """Yield (track_index, item) for every clip on every audio track."""
        tl = timeline or self.timeline
        for track in range(1, tl.GetTrackCount("audio") + 1):
            for item in tl.GetItemListInTrack("audio", track) or []:
                yield track, item

    def iter_media_pool_clips(self, folder: Any = None) -> Iterator[Any]:
        """Yield every clip in the Media Pool, recursing into subfolders."""
        root = folder or self.media_pool.GetRootFolder()
        for clip in root.GetClipList() or []:
            yield clip
        for sub in root.GetSubFolderList() or []:
            yield from self.iter_media_pool_clips(sub)

    # -- lookups -------------------------------------------------------------

    def find_timeline(self, name: str) -> Optional[Any]:
        """Find a timeline by exact name in the current project."""
        proj = self.project
        for i in range(1, proj.GetTimelineCount() + 1):
            tl = proj.GetTimelineByIndex(i)
            if tl and tl.GetName() == name:
                return tl
        return None

    def summary(self) -> dict:
        """Quick, safe snapshot of the current session (for agent verification)."""
        proj = self.project
        info = {
            "project": proj.GetName(),
            "page": self.page(),
            "timeline_count": proj.GetTimelineCount(),
        }
        tl = proj.GetCurrentTimeline()
        if tl:
            from .timecode import parse_fps

            try:
                fps: Optional[float] = parse_fps(tl.GetSetting("timelineFrameRate"))
            except Exception:
                fps = None
            info.update(
                timeline=tl.GetName(),
                fps=fps,
                video_tracks=tl.GetTrackCount("video"),
                audio_tracks=tl.GetTrackCount("audio"),
                start_frame=tl.GetStartFrame(),
                end_frame=tl.GetEndFrame(),
                markers=len(tl.GetMarkers() or {}),
            )
        return info


def connect(need_project: bool = True) -> ResolveKit:
    """Connect to the running Resolve instance and return a ResolveKit.

    Raises ResolveConnectionError with actionable hints on failure.
    """
    dvr = load_resolve_module()
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise ResolveConnectionError(
            "Could not connect to DaVinci Resolve.\n"
            "  - Is Resolve running?\n"
            "  - Preferences > General > External scripting using > Local\n"
            "  - External scripting requires Resolve Studio."
        )
    kit = ResolveKit(resolve=resolve)
    if need_project:
        _ = kit.project  # raises if nothing open
    return kit
