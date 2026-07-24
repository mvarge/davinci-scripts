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
