# DaVinci Resolve 20 Python Scripting Guide

## My Environment

- Resolve Version: 20.0.1 Build 6 (Studio)
- OS: macOS
- Python: System python3
- Working Font: Helvetica Neue

## Setup

Module path:

    import sys
    sys.path.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
    import DaVinciResolveScript as dvr

The native library lives at:

    /Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so

Resolve setting required:

    Preferences → General → External scripting using → Local

Resolve must be running with a project open before any script will work.

## Connecting to Resolve

    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()

If resolve is None:
- Resolve isn't running
- External scripting not set to "Local"
- Restart Resolve after changing the setting

## Object Hierarchy

    resolve
      └── GetProjectManager()
            └── GetCurrentProject()
                  ├── GetName()
                  ├── GetMediaPool()
                  │     ├── GetRootFolder()
                  │     ├── SetCurrentFolder()
                  │     └── CreateEmptyTimeline()  ← UNRELIABLE on fresh projects
                  ├── GetCurrentTimeline()
                  │     ├── GetItemListInTrack("video", 1)  → list of clips
                  │     ├── GetTrackCount("video")
                  │     └── GetSetting("timelineFrameRate")
                  └── GetTimelineByIndex(n)

Two separate APIs exist:
1. Resolve API - project, timeline, media pool, render. Root: resolve
2. Fusion API - node graphs, tools, animations. Root: comp
They overlap on the Fusion page but are different hierarchies.

## Getting a Fusion Composition

    timeline = project.GetCurrentTimeline()
    clips = timeline.GetItemListInTrack("video", 1)
    clip = clips[0]
    comp = clip.GetFusionCompByIndex(1)

Prerequisites:
- Timeline must exist (create manually if CreateEmptyTimeline fails)
- A Fusion Composition generator must be on the timeline
- Edit page, Effects Library, Toolbox, Generators, Fusion Composition
- Drag onto video track manually (API cannot insert this)

## Fusion Nodes

Switching to Fusion page:

    resolve.OpenPage("fusion")

Adding tools:

    bg = comp.AddTool("Background", -3, 0)
    text = comp.AddTool("TextPlus", -1, 0)
    merge = comp.AddTool("Merge", 1, 0)
    glow = comp.AddTool("SoftGlow", 3, 0)
    grain = comp.AddTool("FilmGrain", 5, 0)
    mask = comp.AddTool("RectangleMask", -7, 2)

Two numbers after tool type are x,y position in node graph.

Naming nodes:

    bg.SetAttrs({"TOOLS_Name": "MyBackground"})
## Animation / Keyframes — CRITICAL FINDINGS

This is the hardest part. Most documented approaches do not work
in Resolve 20 via external Python.

### What DOES NOT work

    # Python dict assignment
    tool.Blend = {0: 0.0, 20: 1.0}

    # Python SetInput with time alone (last value wins, no keyframes)
    tool.SetInput("Blend", 0.0, 0)
    tool.SetInput("Blend", 1.0, 20)

    # Lua BezierSpline with values in single call (unreliable)
    # Lua comp:BezierSpline with comp: prefix
    # Lua BezierSpline direct assignment
    # Lua comp:Path for point animation

### What DOES work — Two-step method

Step 1: Create empty BezierSpline via Lua
Step 2: Set keyframe values via Python SetInput with time parameter

    import time

    def animate(tool_name, input_name, keyframes):
        comp.Execute(
            f'comp:FindTool("{tool_name}"):SetInput("{input_name}", BezierSpline{{}})'
        )
        time.sleep(0.15)
        tool = comp.FindTool(tool_name)
        for frame, value in keyframes.items():
            tool.SetInput(input_name, value, frame)
        time.sleep(0.1)

Usage:

    animate("MergeNode", "Blend", {0: 0.0, 25: 1.0})
    animate("TitleGlow", "Gain", {0: 0.0, 25: 1.0, 50: 0.25})
    animate("MainTitle", "Size", {0: 0.04, 30: 0.08})
    animate("LineMask", "Width", {0: 0.0, 30: 0.4})

The time.sleep calls are necessary. Without them Resolve does not
reliably commit the spline before Python tries to write keyframes.

## Executing Lua from Python

    comp.Execute("""
        local tool = comp:FindTool("ToolName")
        print("hello from lua")
    """)

Lua print() output goes to Fusion console (Workspace → Console),
not to your Python terminal.

## Inspecting Tools

BMD docs are incomplete. Use this to dump all inputs on any tool:

    tools = comp.GetToolList()
    for idx, tool in tools.items():
        print(f"{tool.Name} ({tool.ID})")
        inputs = tool.GetInputList()
        for iid, inp in inputs.items():
            attrs = inp.GetAttrs()
            name = attrs.get("INPS_Name", "?")
            connected = inp.GetConnectedOutput()
            if connected:
                source = connected.GetTool()
                print(f"  {iid} ({name}): <- {source.Name}")
            else:
                data_type = attrs.get("INPS_DataType", "")
                if data_type in ["Number", "Point", "Text"]:
                    val = inp[comp.CurrentTime]
                    print(f"  {iid} ({name}): = {val}")
## Available Resolve Methods

    resolve: DeleteLayoutPreset, ExportBurnInPreset,
    ExportLayoutPreset, ExportRenderPreset, Fusion,
    GetCurrentPage, GetKeyframeMode, GetMediaStorage,
    GetProductName, GetProjectManager, GetVersion,
    GetVersionString, ImportBurnInPreset, ImportLayoutPreset,
    ImportRenderPreset, LoadLayoutPreset, OpenPage, Print,
    Quit, SaveLayoutPreset, SetHighPriority, SetKeyframeMode,
    UpdateLayoutPreset

    project: AddColorGroup, AddRenderJob, DeleteAllRenderJobs,
    DeleteColorGroup, DeleteRenderJob, DeleteRenderPreset,
    ExportCurrentFrameAsStill, GetColorGroupsList,
    GetCurrentRenderFormatAndCodec, GetCurrentRenderMode,
    GetCurrentTimeline, GetGallery, GetMediaPool, GetName,
    GetPresetList, GetPresets, GetRenderCodecs, GetRenderFormats,
    GetRenderJobList, GetRenderJobStatus, GetRenderPresetList,
    GetRenderResolutions, GetSetting, GetTimelineByIndex,
    GetTimelineCount, GetUniqueId, IsRenderingInProgress,
    LoadRenderPreset, SaveAsNewRenderPreset,
    SetCurrentRenderFormatAndCodec, SetCurrentRenderMode,
    SetCurrentTimeline, SetName, SetRenderSettings, SetSetting,
    StartRendering, StopRendering

    clip: AddFlag, AddFusionComp, AddMarker, ClearClipColor,
    ClearFlags, DeleteFusionCompByName, DeleteMarkerAtFrame,
    ExportFusionComp, GetClipColor, GetClipEnabled, GetDuration,
    GetEnd, GetFusionCompByIndex, GetFusionCompByName,
    GetFusionCompCount, GetFusionCompNameList, GetMarkers,
    GetMediaPoolItem, GetName, GetProperty, GetStart, GetUniqueId,
    ImportFusionComp, LoadFusionCompByName, SetClipColor,
    SetClipEnabled, SetProperty

    comp: AbortRender, ActiveTool, AddTool, AutoPos, ClearUndo,
    Copy, CopySettings, CurrentFrame, CurrentTime, EndUndo,
    Execute, ExecuteFile, Export, FindTool, FindToolByID,
    GetConsoleHistory, GetData, GetFrameList, GetID, GetMarkers,
    GetNextKeyTime, GetPrefs, GetPrevKeyTime, GetPreviewList,
    GetReg, GetToolList, GetUndoStack, GetViewList, IsLocked,
    IsPlaying, IsRendering, Lock, Loop, Paste, Play, Print,
    Redo, Render, Save, SaveAs, SetActiveTool, SetData, SetPrefs,
    StartUndo, Stop, Undo, Unlock

## Known Tool IDs

    Background        - solid color or gradient
    TextPlus          - text with full styling
    Merge             - composites foreground over background
    SoftGlow          - glow/bloom effect
    FilmGrain         - adds film grain texture
    RectangleMask     - rectangular mask shape
    EllipseMask       - elliptical mask shape
    DirectionalBlur   - motion blur in a direction
    Transform         - move, scale, rotate
    ColorCorrector    - color grading
    BrightnessContrast - brightness/contrast
    MediaOut          - output node (do not delete)
    MediaIn           - input node (for timeline clips)
## Key Input Names by Tool

Background:
    TopLeftRed, TopLeftGreen, TopLeftBlue, TopLeftAlpha

TextPlus:
    StyledText - the text content
    Font - font family name (must match exactly)
    Style - e.g. "Bold"
    Size - float, e.g. 0.08
    Red1, Green1, Blue1, Alpha1 - text color
    CharacterSpacing - float, e.g. 1.05
    LayoutCenter - point, position of text block
    WriteOnEnd - float 0-1, for write-on animation

Merge:
    Background - connect to background image output
    Foreground - connect to foreground image output
    Blend - float 0-1, opacity of foreground
    Center - point, position of foreground

SoftGlow:
    Input - connect to image output
    Gain - float, glow intensity
    GlowSize - float, glow radius
    Threshold - float, brightness cutoff

FilmGrain:
    Input - connect to image output
    Strength - float, grain amount
    Size - float, grain size

RectangleMask:
    Width - float
    Height - float
    Center - point

## Boilerplate Template

    import sys, time
    sys.path.append(
        "/Library/Application Support/Blackmagic Design"
        "/DaVinci Resolve/Developer/Scripting/Modules"
    )
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    clip = timeline.GetItemListInTrack("video", 1)[0]
    comp = clip.GetFusionCompByIndex(1)
    resolve.OpenPage("fusion")

    def animate(tool_name, input_name, keyframes):
        comp.Execute(
            f'comp:FindTool("{tool_name}")'
            f':SetInput("{input_name}", BezierSpline{{}})'
        )
        time.sleep(0.15)
        tool = comp.FindTool(tool_name)
        for frame, value in keyframes.items():
            tool.SetInput(input_name, value, frame)
        time.sleep(0.1)

    def find_font():
        tmp = comp.AddTool("TextPlus", -10, -10)
        for f in [
            "Helvetica Neue", "Helvetica",
            "Arial", "Futura", "Avenir"
        ]:
            tmp.Font = f
            if tmp.GetInput("Font", 0) == f:
                tmp.Delete()
                return f
        tmp.Delete()
        return "Helvetica"

    def clear_comp():
        tools = comp.GetToolList()
        for idx, tool in tools.items():
            if tool.ID != "MediaOut":
                tool.Delete()

## Known Quirks and Gotchas

1. CreateEmptyTimeline fails on fresh projects with no
   existing timelines. Create the first timeline manually
   via File, New Timeline.

2. Cannot programmatically add a Fusion Composition
   generator to a timeline. Must drag manually from
   Effects Library, Toolbox, Generators, Fusion Composition.

3. Fonts must match exactly or TextPlus renders black
   with no error in Python. Check Fusion console for
   font not found message.

4. Keyframes require the two-step method: create empty
   BezierSpline via Lua then set values via Python
   SetInput. Neither step works alone.

5. time.sleep between creating the spline and setting
   keyframes is required. 0.15s works reliably.

6. comp.Lock/Unlock speeds up bulk node creation but
   do NOT lock when setting keyframes.

7. Lua print output goes to Fusion console
   (Workspace, Console) not to Python terminal.

8. Press 1 on keyboard with a node selected to assign
   it to the left viewer. Without this the viewer
   stays black even if everything is wired correctly.

9. comp.SetActiveTool selects a node but does not
   always assign it to a viewer. Keyboard 1 is
   more reliable.

10. Point inputs use dict format {1: x, 2: y} not
    a list or tuple.

## How We Discovered All This

We tested systematically by:
1. Running test_connection.py to verify Python to
   Resolve communication works
2. Using explore_fusion.py to dump all tool inputs
   and their current values, building our own API
   reference since BMD docs are incomplete
3. Running keyframe_bruteforce.py testing 5 different
   keyframe methods to find the one that actually
   works in Resolve 20
4. Using debug_comp.py to inspect connections and
   verify nodes were wired correctly

The explore pattern (dump GetInputList with GetAttrs
on each input) is the most valuable technique for
figuring out any new tool type. Add a tool manually
in Fusion, then run the explorer to see all its
input names and current values.

## Known API Pitfalls (live-verified)

Distilled from live-verified findings in the davinci-resolve-mcp project (MIT, samuelgursky) plus our own testing. Verified against Resolve Studio 21.0 unless noted.

### Markers & timecode

- **Marker frameIds are timeline-relative** (frame 0 = first frame of the
  timeline), but `GetCurrentTimecode` and the UI show absolute timecode.
  `AddMarker` accepts an absolute frame without validation and `GetMarkers()`
  echoes it back — the marker just lands past the end of the timeline and is
  invisible in the UI. Always subtract `GetStartFrame()` before adding.
- **`GetSetting("timelineFrameRate")` returns a string**, and not always a
  clean one. Don't `int()` it blindly — extract the numeric part (regex or
  equivalent) and go through `float()`.

### Return values you cannot trust

The general defense: **verify by readback**. Re-read the actual post-state
instead of trusting the boolean; a `True` that readback contradicts is the
real failure signal.

- **Many setters return `True` regardless of effect.** Example:
  `SetClipProperty('Reel Name', ...)` returns `True` but the value is silently
  dropped on read-back when the project derives reel names automatically
  (General Options > "Assist using reel names"). Read the property back and
  compare.
- **`MediaPool.AutoSyncAudio` returns a boolean unrelated to whether clips
  actually linked.** Verify by reading each clip's `'Synced Audio'` property.
- **`ProjectManager.DeleteProject` is flaky on the first attempt** and returns
  `False` (no deletion) when the target is — or recently was — the current
  project. Load/close away from the target first, then retry.
- **Fusion `Composition.Paste()` with an in-memory `SaveSettings()` table
  fails silently** across the Python bridge (no node created). Round-trip
  through a temp `.setting` *file* (`SaveSettings(path)` / `LoadSettings(path)`)
  instead.
- `ProjectManager.CreateProject` returns `None` and pops a **modal "Save
  Current Project" dialog** when a dirty Untitled project blocks the switch.
  `CloseProject(current)` first to discard it without a prompt.

### Missing & fabricated APIs

- **`hasattr()`/`getattr()` on any Resolve object always succeed** — the
  Python bridge fabricates a callable for *any* attribute name, so
  `hasattr(tl, 'Razor')` is `True` even though no such method exists (calling
  it returns `None`/`False` with no error). Test membership against
  `dir(obj)` instead; it lists only the real methods.
- **No `GetTimelineByName`.** Iterate
  `GetTimelineByIndex(1..GetTimelineCount())` and compare names yourself.
- **No razor/blade/split**, and **no trim/move/duration setters** on
  `TimelineItem` (`GetStart`/`GetEnd`/offsets are getters only). Rebuild via
  `AppendToTimeline` clipInfos with the desired in/out/record frames, or edit
  in the UI.
- **No clip speed/retime control**: `SetProperty('Speed'|'PlaybackSpeed'|...)`
  all return `False`; only retime *quality* (`RetimeProcess`,
  `MotionEstimation`) is settable. No speed ramps either.
- **No transition API at all** — transitions can't be added, read, copied, or
  cloned; UI-applied ones are invisible to scripts.
- **No insert/overwrite/replace/fit-to-fill edit modes.**
  `MediaPool.AppendToTimeline` (with clipInfo `recordFrame`) is the only
  programmatic placement.
- **No Fairlight mixing**: clip/track volume, pan, EQ, automation, and
  FairlightFX are unscriptable. Beware: `SetProperty('Pan', ...)` succeeds
  because `Pan` is the *video transform* key, not audio pan.
- **No color node-graph editing or primary grade values** — you can't
  add/connect nodes or read/write lift/gamma/gain/curves/windows. Grading is
  limited to CDL (`SetCDL`), whole-grade DRX/LUT application, and `CopyGrades`.

### Project & Media Pool quirks

- Render methods (`AddRenderJob`, `SetRenderSettings`, `LoadRenderPreset`)
  live **on the Project object**, not a separate render interface.
- **No proxy/optimized-media generation** — only `LinkProxyMedia`/
  `UnlinkProxyMedia` for proxies that already exist on disk.
- **No Smart Bin or Power Bin creation** (`AddSubFolder` makes regular bins
  only) and **no folder rename** (create/delete/move only).
- **No native multicam clip creation** — you can stack angles on tracks, but
  the multicam conversion itself is UI-only.
- `GetClipProperty('Transcription')` returns a **preview** — a trailing
  ellipsis means the transcript was truncated.

### Enum-keyed dict parameters (silent string rejection)

Several calls take dicts keyed by **live enum constants** resolved from the
`resolve` handle — plain string keys/values are silently rejected (call
returns `False`, nothing happens):

- `MediaPool.AutoSyncAudio` (`resolve.AUDIO_SYNC_*` keys)
- `Timeline.CreateSubtitlesFromAudio` (`SUBTITLE_*` keys, `AUTO_CAPTION_*` values)
- `Timeline.Export` (`EXPORT_*` enum *values* — even the string
  `'EXPORT_FCPXML_1_10'` fails; no file is written)
- The cloud project family (`Create/Load/Import/RestoreCloudProject`,
  `CLOUD_SETTING_*` / `CLOUD_SYNC_*`)

Always fetch the constants off the live `resolve` object at call time, and
verify the effect afterward (file exists, track count changed, etc.).

### Timeline editing quirks

- **`AppendToTimeline` clipInfo `endFrame` is EXCLUSIVE**: item duration is
  `endFrame - startFrame`. Assuming an inclusive bound drifts one frame per
  clip — advancing a record cursor by `(end - start + 1)` leaves 1-frame holes.
  Treat `[startFrame, endFrame)` as half-open everywhere.
- **`Insert*IntoTimeline` (titles/generators/Fusion comps) take no track
  index** — they always land on the Source Track Selector's target (V1 in
  practice), there's no API to read/set that selector, and locking V1 makes
  the insert *fail* rather than fall through to V2. Inserted titles/generators
  also can't be moved afterward (no MediaPoolItem).
- **`GrabStill`/`ExportStills` need settle time and don't report the output
  filename.** GrabStill requires the Color page with a clip under the
  playhead; ExportStills wants the Gallery open. Sleep briefly (~0.3–0.5 s)
  between grab, export, and filesystem checks, and detect the written file by
  diffing a directory listing taken before the export.
- **`Graph.SetLUT` resolves paths only against the master LUT directory** —
  a basename or even an absolute path into the per-user LUT dir returns
  `False`. Copy the LUT into a subfolder of the master dir, `RefreshLUTList()`,
  and pass the master-relative path.
