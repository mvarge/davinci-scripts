# DaVinci Resolve Python Scripting — Internal Reference

> Built from: personal experimentation (RESOLVE_SCRIPTING_GUIDE.md) + web research (v20.3 API docs)
> Last updated: 2026-03-14
> Environment: Resolve 20.0.1 Studio, macOS, Python 3 (system)

---

## 1. Setup & Connection

```python
import sys, time
sys.path.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
import DaVinciResolveScript as dvr

resolve = dvr.scriptapp("Resolve")
project = resolve.GetProjectManager().GetCurrentProject()
timeline = project.GetCurrentTimeline()
```

**Requirements:**
- Resolve must be running with a project open
- Preferences → General → External scripting → Local
- Native lib: `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so`

**Troubleshooting `resolve is None`:**
- Resolve isn't running
- External scripting not set to "Local"
- Restart Resolve after changing the setting

---

## 2. Object Hierarchy

```
resolve
  └── GetProjectManager()
        ├── GetCurrentProject()         → Project
        ├── GetProjectListInCurrentFolder() → [str]
        ├── CreateProject(name)         → Project
        ├── OpenProject(name)           → Project
        └── GetCurrentFolder()          → str

Project
  ├── GetCurrentTimeline()             → Timeline
  ├── GetTimelineByIndex(n)            → Timeline  (1-based)
  ├── GetTimelineCount()               → int
  ├── SetCurrentTimeline(timeline)     → bool
  ├── GetMediaPool()                   → MediaPool
  ├── GetName() / SetName(name)
  ├── GetSetting(key) / SetSetting(key, value)
  ├── AddRenderJob()                   → jobId (string)
  ├── StartRendering()                 → bool
  ├── IsRenderingInProgress()          → bool
  └── DeleteAllRenderJobs()            → bool

Timeline
  ├── GetName() / SetName(name)
  ├── GetItemListInTrack(type, idx)    → [TimelineItem]  type="video"|"audio"|"subtitle"
  ├── GetTrackCount(type)              → int
  ├── GetSetting(key)                  → str
  ├── GetStartFrame() / GetEndFrame()  → int
  ├── AddMarker(frame, color, name, note, duration, customData) → bool
  ├── GetMarkers()                     → {frame: {color,name,note,duration,customData}}
  └── SetClipsLinked([clips], bool)    → bool

TimelineItem (clip on timeline)
  ├── GetName()
  ├── GetStart() / GetEnd() / GetDuration()  → int (timeline frames)
  ├── GetSourceStartFrame() / GetSourceEndFrame() → int
  ├── GetFusionCompByIndex(1)          → Comp
  ├── GetFusionCompCount()             → int
  ├── AddFusionComp()                  → Comp
  ├── GetMediaPoolItem()               → MediaPoolItem
  ├── SetProperty(key, value)          → bool
  ├── GetProperty(key)                 → value
  ├── AddMarker(...)                   → bool
  ├── SetLUT(nodeIndex, lutPath)       → bool   (Color page, 1-based node)
  ├── AddVersion(name, type)           → bool   (type 0=local, 1=remote)
  └── LoadVersionByName(name, type)   → bool

MediaPool
  ├── GetRootFolder()                  → Folder
  ├── GetCurrentFolder()               → Folder
  ├── SetCurrentFolder(folder)         → bool
  ├── AddClipMattesToMediaPool([paths], stereoEye) → [MediaPoolItem]
  ├── ImportMedia([paths])             → [MediaPoolItem]
  ├── CreateEmptyTimeline(name)        → Timeline  ⚠ UNRELIABLE on fresh projects
  └── CreateTimelineFromClips(name, [clips]) → Timeline

MediaPoolItem
  ├── GetName() / GetClipProperty(key)
  ├── SetClipProperty(key, value)
  ├── GetMediaId()
  └── GetUniqueId()

Folder
  ├── GetName()
  ├── GetClipList()                    → [MediaPoolItem]
  └── GetSubFolderList()               → [Folder]
```

---

## 3. Fusion Composition Access

```python
# Get comp from first clip on video track 1
clip = timeline.GetItemListInTrack("video", 1)[0]
comp = clip.GetFusionCompByIndex(1)

# Switch to Fusion page
resolve.OpenPage("fusion")
```

**Prerequisites:**
- Timeline must exist (create manually if `CreateEmptyTimeline` fails on fresh project)
- A **Fusion Composition generator** must be on the timeline
  - Effects Library → Toolbox → Generators → Fusion Composition → drag to video track
  - ⚠ Cannot be inserted via API

---

## 4. Fusion Node Operations

### Adding Nodes

```python
bg     = comp.AddTool("Background",      -3,  0)
text   = comp.AddTool("TextPlus",        -1,  0)
merge  = comp.AddTool("Merge",            1,  0)
glow   = comp.AddTool("SoftGlow",         3,  0)
grain  = comp.AddTool("FilmGrain",        5,  0)
mask   = comp.AddTool("RectangleMask",   -7,  2)
```

Coordinates are x,y in the node graph (visual layout only).

### Naming Nodes

```python
bg.SetAttrs({"TOOLS_Name": "MyBackground"})
```

### Connecting Nodes

```python
merge.Background = bg.Output
merge.Foreground = text.Output
glow.Input = merge.Output
```

### Deleting Nodes

```python
tools = comp.GetToolList()
for idx, tool in tools.items():
    if tool.ID != "MediaOut":
        tool.Delete()
```

### Finding Nodes

```python
tool = comp.FindTool("NodeName")
tool = comp.FindToolByID("TextPlus")   # finds first of that type
```

---

## 5. Animation / Keyframes — CRITICAL

### ❌ What Does NOT Work (Resolve 20, external Python)

```python
tool.Blend = {0: 0.0, 20: 1.0}                  # dict assignment
tool.SetInput("Blend", 0.0, 0)                    # SetInput alone (last value wins)
```

### ✅ Two-Step Method (WORKS)

Step 1: Create empty BezierSpline via Lua
Step 2: Set keyframe values via Python SetInput

```python
import time

def animate(tool_name, input_name, keyframes):
    comp.Execute(
        f'comp:FindTool("{tool_name}"):SetInput("{input_name}", BezierSpline{{}})'
    )
    time.sleep(0.15)   # REQUIRED — Resolve must commit the spline first
    tool = comp.FindTool(tool_name)
    for frame, value in keyframes.items():
        tool.SetInput(input_name, value, frame)
    time.sleep(0.1)

# Examples
animate("MergeNode",  "Blend",     {0: 0.0, 25: 1.0})
animate("TitleGlow",  "Gain",      {0: 0.0, 25: 1.0, 50: 0.25})
animate("MainTitle",  "Size",      {0: 0.04, 30: 0.08})
animate("LineMask",   "Width",     {0: 0.0, 30: 0.4})
```

### Point Inputs (Position)

```python
# Point inputs use {1: x, 2: y} dict — NOT a tuple/list
tool.SetInput("Center", {1: 0.5, 2: 0.5}, 0)
```

---

## 6. Executing Lua from Python

```python
comp.Execute("""
    local tool = comp:FindTool("ToolName")
    tool:SetInput("Blend", BezierSpline{})
    print("done from lua")
""")
```

**Note:** `print()` in Lua goes to Fusion Console (Workspace → Console), NOT to Python terminal.

---

## 7. Inspecting Tool Inputs

BMD docs are incomplete. Use this pattern to discover any tool's inputs:

```python
tools = comp.GetToolList()
for idx, tool in tools.items():
    print(f"\n{tool.Name} ({tool.ID})")
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
                print(f"  {iid} ({name}): {data_type} = {val}")
```

---

## 8. Known Tool IDs & Key Inputs

### Background
```
TopLeftRed, TopLeftGreen, TopLeftBlue, TopLeftAlpha
Type: 0=solid, 1=gradient
```

### TextPlus
```
StyledText        string  — the text content
Font              string  — must match exactly (e.g. "Helvetica Neue")
Style             string  — e.g. "Bold"
Size              float   — e.g. 0.08
Red1,Green1,Blue1,Alpha1  — text color
CharacterSpacing  float   — e.g. 1.05
LayoutCenter      point   — {1: x, 2: y}
WriteOnEnd        float   — 0-1, write-on animation
```

### Merge
```
Background        — connect to bg output
Foreground        — connect to fg output
Blend             float 0-1
Center            point
```

### SoftGlow
```
Input             — connect to image output
Gain              float — glow intensity
GlowSize          float — glow radius
Threshold         float — brightness cutoff
```

### FilmGrain
```
Input             — connect to image output
Strength          float
Size              float
```

### RectangleMask / EllipseMask
```
Width, Height     float
Center            point
```

### Transform
```
Center            point
Size              float — uniform scale
Angle             float — degrees
```

### ColorCorrector
```
MasterSaturation, MasterBrightness, MasterContrast
LowSaturation, MidSaturation, HighSaturation
```

### BrightnessContrast
```
Brightness        float
Contrast          float
```

---

## 9. Render / Export API

```python
# Set render format and codec
project.SetCurrentRenderFormatAndCodec("mp4", "H264")

# Set render settings
project.SetRenderSettings({
    "SelectAllFrames": True,            # render full timeline
    "TargetDir":       "/path/to/out",
    "CustomName":      "output_name",
    "UniqueFilenameStyle": 0,           # 0=prefix, 1=suffix
    "ExportVideo": True,
    "ExportAudio": True,
    # Optional: render range
    "MarkIn":  0,
    "MarkOut": 100,
})

# Add job to queue and render
jobId = project.AddRenderJob()
project.StartRendering(jobId)

# Wait for completion
while project.IsRenderingInProgress():
    time.sleep(1)

# Check status
status = project.GetRenderJobStatus(jobId)
# status["JobStatus"] → "Complete" | "Failed" | "Cancelled"
# status["CompletionPercentage"] → 0-100
```

### Common Format/Codec Pairs
```
"mp4"  / "H264"
"mp4"  / "H265"
"mov"  / "ProRes422"
"mov"  / "ProRes4444"
"mxf"  / "DNxHD"
"dpx"  / "RGB16"
"exr"  / "RGB16"
```

### Get Available Formats/Codecs
```python
formats = project.GetRenderFormats()   # dict of format → display name
codecs  = project.GetRenderCodecs("mp4")  # codecs available for format
presets = project.GetRenderPresetList()
```

---

## 10. Timeline Settings Keys

```python
timeline.GetSetting("timelineFrameRate")      # "24", "25", "29.97", etc.
timeline.GetSetting("timelineResolutionWidth")
timeline.GetSetting("timelineResolutionHeight")
timeline.GetSetting("timelinePlaybackFrameRate")
```

---

## 11. Project Settings Keys

```python
project.GetSetting("timelineFrameRate")
project.GetSetting("colorScienceMode")         # "davinciYRGB", "davinciYRGBColorManagedV2"
project.GetSetting("colorAsShotDefault")
project.GetSetting("inputDRT") / "outputDRT"
```

---

## 12. MediaPool & Import

```python
mp = project.GetMediaPool()
root = mp.GetRootFolder()

# Import files
items = mp.ImportMedia(["/path/to/file.mp4", "/path/to/other.mov"])

# Create subfolder
# (no direct API — use SetCurrentFolder + CreateEmptyTimeline workarounds)
# Folders are managed via GetRootFolder().GetSubFolderList()

# Create timeline from clips
timeline = mp.CreateTimelineFromClips("MyTimeline", items)
```

---

## 13. Markers

```python
# Add marker to timeline
timeline.AddMarker(
    frameId=100,
    color="Blue",        # Red,Orange,Apricot,Yellow,Lime,Mint,Cyan,Teal,Navy,Blue,Purple,Violet,Pink,Fuchsia,Rose,Lavender,Sky,Chocolate,Tan,Warm Gray,Cool Gray,White
    name="My Marker",
    note="Some note",
    duration=1,
    customData=""
)

# Get all markers
markers = timeline.GetMarkers()
# { frame: {"color": "Blue", "name": "...", "note": "...", "duration": 1, "customData": ""} }

# Delete marker
timeline.DeleteMarkerAtFrame(100)
timeline.DeleteMarkersByColor("Blue")
```

---

## 14. Pages

```python
resolve.GetCurrentPage()   # "media"|"cut"|"edit"|"fusion"|"color"|"fairlight"|"deliver"
resolve.OpenPage("fusion") # switches to that page
```

---

## 15. Boilerplate Template

```python
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
    for f in ["Helvetica Neue", "Helvetica", "Arial", "Futura", "Avenir"]:
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

def lock_comp(fn):
    """Decorator: lock comp during bulk node creation (speeds things up)."""
    def wrapper(*args, **kwargs):
        comp.Lock()
        try:
            return fn(*args, **kwargs)
        finally:
            comp.Unlock()
    return wrapper
```

---

## 16. Known Quirks & Gotchas

| # | Issue | Workaround |
|---|-------|------------|
| 1 | `CreateEmptyTimeline` fails on fresh project with no timelines | Create first timeline manually via File → New Timeline |
| 2 | Cannot add Fusion Composition generator via API | Drag from Effects Library → Toolbox → Generators → Fusion Composition |
| 3 | Wrong font name → TextPlus renders black, no Python error | Check Fusion Console for font error; use `find_font()` helper |
| 4 | Keyframe dict assignment `{0: val}` does nothing | Use two-step: Lua BezierSpline{} + Python SetInput per frame |
| 5 | `time.sleep(0.15)` between spline creation and keyframe writing is required | Without it, Resolve doesn't reliably commit the spline |
| 6 | `comp.Lock()` speeds up bulk node creation | Do NOT lock when setting keyframes — it breaks them |
| 7 | Lua `print()` goes to Fusion Console, not Python terminal | Workspace → Console to view Lua output |
| 8 | Viewer stays black even if nodes are wired | Press `1` on keyboard with node selected to assign to viewer |
| 9 | `comp.SetActiveTool()` doesn't always assign to viewer | Keyboard shortcut `1` is more reliable |
| 10 | Point inputs `{1: x, 2: y}` — not tuple/list | Always use dict format for Point DataType |
| 11 | `StartRendering()` with index is deprecated | Use `StartRendering(jobId)` with unique string job id |
| 12 | `SetLUT()` node index is 1-based (changed in v16.2) | Use `SetLUT(1, path)` for first node |

---

## 17. Exploration Workflow

When encountering a new tool type:

1. Add the tool manually in Fusion UI
2. Run the input inspector (Section 7) to dump all inputs
3. Note the `INPS_DataType` for each input:
   - `Number` → float/int, set directly
   - `Point`  → `{1: x, 2: y}` dict
   - `Text`   → string
   - `Image`  → connected output from another tool
4. For animation: use `animate()` helper (Section 5)
5. For connections: `tool.InputName = other_tool.Output`

**Useful Lua introspection in Console:**

```lua
-- List all tools in comp
for i, t in pairs(comp:GetToolList()) do print(i, t.Name, t.ID) end

-- Dump inputs of a tool
local t = comp:FindTool("ToolName")
for i, inp in pairs(t:GetInputList()) do
    local a = inp:GetAttrs()
    print(i, a.INPS_Name, a.INPS_DataType)
end
```

---

## 18. API Gaps / Limitations (updated for Resolve 21, live-verified)

- ❌ Cannot create first timeline on a completely fresh project via API
- ❌ No direct API for audio track manipulation in Fairlight page
- ❌ Subtitle caption text is READ-ONLY: `GetItemListInTrack("subtitle", n)` +
  `GetName()` return real text/timing, but `SetName()` returns False and
  changes nothing (verified by readback, 21.0.3). No caption create/edit/split.
  Note: `CreateSubtitlesFromAudio()` DOES exist for generating the track, and
  per-word animation is a stock UI feature (drag an "Animated" title template
  onto the subtitle track header) — not an API problem to solve.
- ❌ Fusion node keyframe dict assignment broken in external Python (use two-step)
- ❌ No official Fusion node documentation — must use input inspector
- ✅ `InsertFusionCompositionIntoTimeline`, `InsertFusionTitleIntoTimeline`,
  `InsertGeneratorIntoTimeline` etc. exist and resolve live (an earlier
  version of this file claimed Fusion comps couldn't be inserted — wrong;
  but they always land on V1, see scripting guide "Timeline editing quirks")
- ✅ Can render and export via Deliver API
- ✅ Can manage media pool, folders, and clips
- ✅ Can manipulate timeline items (markers, LUTs, versions, properties)
- ✅ Can build full Fusion compositions programmatically (with workarounds)
