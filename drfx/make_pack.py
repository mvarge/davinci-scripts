#!/usr/bin/env python3
"""Generate DaVinci Resolve Edit-page Fusion transitions (.setting) and pack
them into an installable .drfx archive.

Spec distilled from dissecting working packs + live ground-truth probes of
Resolve 21's own serializations (Loader/TimeStretcher/Merge/Background were
generated in a live comp via resolve_kit and SaveSettings, then copied here):

- A transition is a MacroOperator with MainInput1 (A/outgoing clip),
  MainInput2 (B/incoming clip) and MainOutput1, placed under
  Edit/Transitions/<Pack>/ inside a zip renamed .drfx. No manifest;
  the filename (minus .setting) is the Effects Library display name.
- All animation uses `time/comp.RenderEnd` expressions (normalized 0..1
  progress) so transitions rescale when trimmed on the timeline.
  Frame-keyed BezierSplines do NOT scale — never used.
- Stock Fusion tools only — ResolveFX OFX nodes are version-pinned.
- Fusion's Loader cannot decode HEVC .mov (probe: Length=0) but handles
  JPEG sequences (probe: Length=28). Film-burn media therefore lives as
  JPEG sequences on disk; .setting files reference absolute paths, so the
  film-burn transitions are machine-specific (fine for personal use).

Usage:
    python3 drfx/make_pack.py                 # build dist/<pack>.drfx
    python3 drfx/make_pack.py --install       # build + copy into Resolve Templates
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

PACK_NAME = "mvarge Essentials"
DIST = os.path.join(os.path.dirname(__file__), "..", "dist")

BURN_SEQ_DIR = os.path.expanduser(
    "~/Documents/Media/Personal/Videos/Filmburns/sequences"
)
# (folder, first-file, frame_count) — probed via ffprobe/Loader
BURNS = [
    ("burn1", "burn1.0001.jpg", 28),
    ("burn2", "burn2.0001.jpg", 29),
    ("burn3", "burn3.0001.jpg", 28),
]

# Normalized progress 0..1 across the transition, whatever its length.
T = "time/comp.RenderEnd"

# Easing snippets (inline, single-line, referencing T)
EASE_IN_CUBIC_FIRST_HALF = f"((2*{T})^3)"          # 0..1 over first half
EASE_OUT_CUBIC_SECOND_HALF = f"((2*(1-{T}))^3)"    # 1..0 over second half
ENVELOPE = f"iif({T} < 0.5, {EASE_IN_CUBIC_FIRST_HALF}, {EASE_OUT_CUBIC_SECOND_HALF})"
HARD_SWITCH = f"iif({T} < 0.5, 0, 1)"

LUT_COLORS = [(204, 0, 0), (0, 204, 0), (0, 0, 204), (180, 180, 180)]


# ---------------------------------------------------------------------------
# Emission helpers
# ---------------------------------------------------------------------------

def lut_boilerplate(prefix: str) -> str:
    """The four default linear LUTBezier splines a Custom tool expects."""
    chunks = []
    for i, (r, g, b) in enumerate(LUT_COLORS, start=1):
        chunks.append(f"""\
\t\t\t\t{prefix}LUTIn{i} = LUTBezier {{
\t\t\t\t\tKeyColorSplines = {{
\t\t\t\t\t\t[0] = {{
\t\t\t\t\t\t\t[0] = {{ 0, RH = {{ 0.333333333333333, 0.333333333333333 }} }},
\t\t\t\t\t\t\t[1] = {{ 1, LH = {{ 0.666666666666667, 0.666666666666667 }} }}
\t\t\t\t\t\t}}
\t\t\t\t\t}},
\t\t\t\t\tSplineColor = {{ Red = {r}, Green = {g}, Blue = {b} }},
\t\t\t\t\tNameSet = true,
\t\t\t\t}},""")
    return "\n".join(chunks)


def params_tool(numbers: list[tuple[str, float]], exprs: list[tuple[str, str]] = ()) -> str:
    """A Custom tool named Params exposing tunable numbers.

    numbers — (label, default) pairs mapped to NumberIn1..N (user-tunable).
    exprs   — (label, expression) pairs appended after them (computed).
    """
    lines = []
    idx = 0
    for label, default in numbers:
        idx += 1
        lines.append(f'\t\t\t\t\t\tNumberIn{idx} = Input {{ Value = {default}, }},')
    for label, expr in exprs:
        idx += 1
        lines.append(f'\t\t\t\t\t\tNumberIn{idx} = Input {{')
        lines.append(f'\t\t\t\t\t\t\tValue = 0,')
        lines.append(f'\t\t\t\t\t\t\tExpression = "{expr}",')
        lines.append(f'\t\t\t\t\t\t}},')
    for i, (label, _) in enumerate(list(numbers) + [(l, 0) for l, _ in exprs], start=1):
        lines.append(f'\t\t\t\t\t\tNameforNumber{i} = Input {{ Value = "{label}", }},')
    for i in range(idx + 1, 9):
        lines.append(f'\t\t\t\t\t\tShowNumber{i} = Input {{ Value = 0, }},')
    for i in range(1, 5):
        lines.append(f'\t\t\t\t\t\tLUTIn{i} = Input {{ SourceOp = "ParamsLUTIn{i}", Source = "Value", }},')
    body = "\n".join(lines)
    return f"""\
\t\t\t\tParams = Custom {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
{body}
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 0, -66 }} }},
\t\t\t\t}},
{lut_boilerplate("Params")}"""


def instance_input(key: str, source_op: str, source: str, name: str = "",
                   default=None, max_scale=None) -> str:
    fields = [f'\t\t\t\t\tSourceOp = "{source_op}",', f'\t\t\t\t\tSource = "{source}",']
    if name:
        fields.append(f'\t\t\t\t\tName = "{name}",')
    if default is not None:
        fields.append(f'\t\t\t\t\tDefault = {default},')
    if max_scale is not None:
        fields.append(f'\t\t\t\t\tMaxScale = {max_scale},')
    fields.append('\t\t\t\t\tPage = "Controls",')
    body = "\n".join(fields)
    return f"\t\t\t\t{key} = InstanceInput {{\n{body}\n\t\t\t\t}}"


def macro(name: str, main_in1: tuple[str, str], main_in2: tuple[str, str],
          output_op: str, controls: list[tuple], tools_lua: str) -> str:
    """Assemble a complete transition .setting."""
    inputs = [
        f'\t\t\t\tComments = Input {{ Value = "{PACK_NAME} — generated by drfx/make_pack.py", }},',
        f'\t\t\t\tMainInput1 = InstanceInput {{\n\t\t\t\t\tSourceOp = "{main_in1[0]}",\n\t\t\t\t\tSource = "{main_in1[1]}",\n\t\t\t\t}},',
        f'\t\t\t\tMainInput2 = InstanceInput {{\n\t\t\t\t\tSourceOp = "{main_in2[0]}",\n\t\t\t\t\tSource = "{main_in2[1]}",\n\t\t\t\t}},',
    ]
    for i, ctrl in enumerate(controls, start=1):
        inputs.append(instance_input(f"Input{i}", *ctrl) + ",")
    inputs_lua = "\n".join(inputs).rstrip(",")

    return f"""{{
\tTools = ordered() {{
\t\t{name} = MacroOperator {{
\t\t\tCtrlWZoom = false,
\t\t\tNameSet = true,
\t\t\tInputs = ordered() {{
{inputs_lua}
\t\t\t}},
\t\t\tOutputs = {{
\t\t\t\tMainOutput1 = InstanceOutput {{
\t\t\t\t\tSourceOp = "{output_op}",
\t\t\t\t\tSource = "Output",
\t\t\t\t}}
\t\t\t}},
\t\t\tViewInfo = GroupInfo {{ Pos = {{ 0, 0 }} }},
\t\t\tTools = ordered() {{
{tools_lua}
\t\t\t}},
\t\t}}
\t}}
}}
"""


def transform(name: str, inputs: dict[str, str], pos: tuple[int, int],
              source: tuple[str, str] | None = None) -> str:
    lines = []
    for k, v in inputs.items():
        lines.append(f"\t\t\t\t\t\t{k} = {v},")
    if source:
        lines.append(f'\t\t\t\t\t\tInput = Input {{\n\t\t\t\t\t\t\tSourceOp = "{source[0]}",\n\t\t\t\t\t\t\tSource = "{source[1]}",\n\t\t\t\t\t\t}},')
    body = "\n".join(lines)
    return f"""\
\t\t\t\t{name} = Transform {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
{body}
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {pos[0]}, {pos[1]} }} }},
\t\t\t\t}},"""


def expr_input(expr: str, value=0) -> str:
    return f'Input {{ Value = {value}, Expression = "{expr}" }}'


def dissolve(name: str, bg: str, fg: str, mix_expr: str, pos=(0, 33)) -> str:
    return f"""\
\t\t\t\t{name} = Dissolve {{
\t\t\t\t\tTransitions = {{
\t\t\t\t\t\t[0] = "DFTDissolve"
\t\t\t\t\t}},
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tMix = Input {{
\t\t\t\t\t\t\tValue = 0,
\t\t\t\t\t\t\tExpression = "{mix_expr}",
\t\t\t\t\t\t}},
\t\t\t\t\t\tBackground = Input {{
\t\t\t\t\t\t\tSourceOp = "{bg}",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t\tForeground = Input {{
\t\t\t\t\t\t\tSourceOp = "{fg}",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {pos[0]}, {pos[1]} }} }},
\t\t\t\t}},"""


def blur(name: str, source: str, x_expr: str, y_expr: str | None = None,
         pos=(110, 33), last=False) -> str:
    y_line = f'\t\t\t\t\t\tYBlurSize = Input {{ Value = 0, Expression = "{y_expr}" }},\n' if y_expr else ""
    comma = "" if last else ","
    return f"""\
\t\t\t\t{name} = Blur {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tXBlurSize = Input {{
\t\t\t\t\t\t\tValue = 0,
\t\t\t\t\t\t\tExpression = "{x_expr}",
\t\t\t\t\t\t}},
{y_line}\t\t\t\t\t\tInput = Input {{
\t\t\t\t\t\t\tSourceOp = "{source}",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {pos[0]}, {pos[1]} }} }},
\t\t\t\t}}{comma}"""


# ---------------------------------------------------------------------------
# Transition generators
# ---------------------------------------------------------------------------

def zoom_punch_setting() -> str:
    """A-side whips into a zoom, hard cut at midpoint, B-side lands back."""
    size_a = f"iif({T} < 0.5, 1 + Params.NumberIn1 * {EASE_IN_CUBIC_FIRST_HALF}, 1 + Params.NumberIn1)"
    size_b = f"iif({T} < 0.5, 1 + Params.NumberIn1, 1 + Params.NumberIn1 * {EASE_OUT_CUBIC_SECOND_HALF})"

    tools = "\n".join([
        params_tool([("Zoom Amount", 0.35), ("Blur Amount", 1)],
                    [("Envelope", ENVELOPE)]),
        transform("XfA", {
            "Size": expr_input(size_a, 1),
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 0)),
        transform("XfB", {
            "Size": expr_input(size_b, 1),
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 66)),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH),
        blur("PostBlur", "Dissolve1",
             "Params.NumberIn3 * 12 * Params.NumberIn2",
             "Params.NumberIn3 * 12 * Params.NumberIn2", last=True),
    ])
    return macro("ZoomPunch", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Zoom Amount", 0.35, 1),
                  ("Params", "NumberIn2", "Blur Amount", 1, 2)],
                 tools)


def spin_punch_setting() -> str:
    """Rotational sibling of Zoom Punch: whip-rotate into the cut."""
    angle_a = f"iif({T} < 0.5, -Params.NumberIn1 * {EASE_IN_CUBIC_FIRST_HALF}, -Params.NumberIn1)"
    angle_b = f"iif({T} < 0.5, Params.NumberIn1, Params.NumberIn1 * {EASE_OUT_CUBIC_SECOND_HALF})"
    # slight zoom rides the envelope to hide corners during rotation
    size = "1 + Params.NumberIn3 * 0.18"

    tools = "\n".join([
        params_tool([("Spin Degrees", 20), ("Blur Amount", 1)],
                    [("Envelope", ENVELOPE)]),
        transform("XfA", {
            "Angle": expr_input(angle_a),
            "Size": expr_input(size, 1),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 0)),
        transform("XfB", {
            "Angle": expr_input(angle_b),
            "Size": expr_input(size, 1),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 66)),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH),
        blur("PostBlur", "Dissolve1",
             "Params.NumberIn3 * 10 * Params.NumberIn2",
             "Params.NumberIn3 * 10 * Params.NumberIn2", last=True),
    ])
    return macro("SpinPunch", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Spin Degrees", 20, 45),
                  ("Params", "NumberIn2", "Blur Amount", 1, 2)],
                 tools)


def whip_pan_setting(direction: str) -> str:
    """Directional whip: A-side slams offscreen, B-side slams in behind it.
    Mirror edges avoid black gaps; a directional blur sells the speed."""
    dx, dy = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, 1), "Down": (0, -1)}[direction]
    # A: center 0.5 -> 0.5+d (ease-in). B: 0.5-d -> 0.5 (ease-out).
    prog_a = f"0.5*{EASE_IN_CUBIC_FIRST_HALF}"
    prog_b = f"0.5*{EASE_OUT_CUBIC_SECOND_HALF}"
    center_a = (f"Point(0.5 + {dx} * iif({T} < 0.5, {prog_a}, 0.5), "
                f"0.5 + {dy} * iif({T} < 0.5, {prog_a}, 0.5))")
    center_b = (f"Point(0.5 - {dx} * iif({T} < 0.5, 0.5, {prog_b}), "
                f"0.5 - {dy} * iif({T} < 0.5, 0.5, {prog_b}))")
    horizontal = dx != 0
    x_blur = "Params.NumberIn2 * Params.NumberIn1 * 40" if horizontal else "0"
    y_blur = "0" if horizontal else "Params.NumberIn2 * Params.NumberIn1 * 40"

    tools = "\n".join([
        params_tool([("Blur Amount", 1)], [("Envelope", ENVELOPE)]),
        transform("XfA", {
            "Center": expr_input(center_a, "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 0)),
        transform("XfB", {
            "Center": expr_input(center_b, "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 66)),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH),
        blur("PostBlur", "Dissolve1", x_blur, y_blur, last=True),
    ])
    return macro(f"WhipPan{direction}", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Blur Amount", 1, 2)],
                 tools)


def flash_cut_setting() -> str:
    """Hard cut with a white flash blooming at the midpoint."""
    # flash envelope: 0 except +-1/6 of duration around the cut, peak 1
    flash = f"(max(0, 1 - abs(2*{T} - 1) * 3))^2"

    tools = "\n".join([
        params_tool([("Flash Intensity", 1), ("Blur Amount", 0.5)],
                    [("Flash", flash)]),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH, pos=(0, 33)),
        transform("XfA", {"Size": "Input { Value = 1, }"}, (-110, 0)),
        transform("XfB", {"Size": "Input { Value = 1, }"}, (-110, 66)),
        f"""\
\t\t\t\tFlashBG = Background {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tUseFrameFormatSettings = Input {{ Value = 1, }},
\t\t\t\t\t\tTopLeftRed = Input {{ Value = 1, }},
\t\t\t\t\t\tTopLeftGreen = Input {{ Value = 1, }},
\t\t\t\t\t\tTopLeftBlue = Input {{ Value = 1, }},
\t\t\t\t\t\tTopLeftAlpha = Input {{ Value = 1, }},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 0, 99 }} }},
\t\t\t\t}},
\t\t\t\tFlashMerge = Merge {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tBlend = Input {{
\t\t\t\t\t\t\tValue = 0,
\t\t\t\t\t\t\tExpression = "min(1, Params.NumberIn3 * Params.NumberIn1)",
\t\t\t\t\t\t}},
\t\t\t\t\t\tPerformDepthMerge = Input {{ Value = 0, }},
\t\t\t\t\t\tBackground = Input {{
\t\t\t\t\t\t\tSourceOp = "Dissolve1",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t\tForeground = Input {{
\t\t\t\t\t\t\tSourceOp = "FlashBG",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 110, 33 }} }},
\t\t\t\t}},""",
        blur("PostBlur", "FlashMerge",
             "Params.NumberIn3 * 20 * Params.NumberIn2",
             "Params.NumberIn3 * 20 * Params.NumberIn2", pos=(220, 33), last=True),
    ])
    return macro("FlashCut", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Flash Intensity", 1, 2),
                  ("Params", "NumberIn2", "Blur Amount", 0.5, 2)],
                 tools)


def film_burn_setting(seq_folder: str, first_file: str, frames: int,
                      display_index: int) -> str:
    """Marcelo's film burns as self-contained transitions: the burn overlay
    (JPEG sequence, Screen-blended) sweeps the cut; a crossfade hides under
    the burn's peak. TimeStretcher maps burn frames onto normalized progress
    so the burn always spans the transition, whatever its length.
    """
    seq_path = os.path.join(BURN_SEQ_DIR, seq_folder, first_file)
    last = frames - 1
    # remap burn frames across the transition duration
    source_time = f"({T}) * {last}"
    # crossfade weighted toward the burn's brightest moment (middle)
    mix = f"iif({T} < 0.4, 0, iif({T} > 0.6, 1, ({T} - 0.4) * 5))"

    tools = "\n".join([
        params_tool([("Burn Intensity", 1), ("Burn Size", 1),
                     ("Burn Saturation", 1), ("Tint Red", 1),
                     ("Tint Green", 1), ("Tint Blue", 1)]),
        transform("XfA", {"Size": "Input { Value = 1, }"}, (-110, 0)),
        transform("XfB", {"Size": "Input { Value = 1, }"}, (-110, 66)),
        dissolve("Dissolve1", "XfA", "XfB", mix),
        f"""\
\t\t\t\tBurnLoader = Loader {{
\t\t\t\t\tClips = {{
\t\t\t\t\t\tClip {{
\t\t\t\t\t\t\tID = "Clip1",
\t\t\t\t\t\t\tFilename = "{seq_path}",
\t\t\t\t\t\t\tFormatID = "JpegFormat",
\t\t\t\t\t\t\tStartFrame = 1,
\t\t\t\t\t\t\tLength = {frames},
\t\t\t\t\t\t\tLengthSetManually = true,
\t\t\t\t\t\t\tTrimIn = 0,
\t\t\t\t\t\t\tTrimOut = {last},
\t\t\t\t\t\t\tExtendFirst = 0,
\t\t\t\t\t\t\tExtendLast = 1,
\t\t\t\t\t\t\tLoop = 0,
\t\t\t\t\t\t\tAspectMode = 0,
\t\t\t\t\t\t\tDepth = 0,
\t\t\t\t\t\t\tTimeCode = 0,
\t\t\t\t\t\t\tGlobalStart = 0,
\t\t\t\t\t\t\tGlobalEnd = {last}
\t\t\t\t\t\t}}
\t\t\t\t\t}},
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ -110, 132 }} }},
\t\t\t\t}},
\t\t\t\tBurnTime = TimeStretcher {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tSourceTime = Input {{
\t\t\t\t\t\t\tValue = 0,
\t\t\t\t\t\t\tExpression = "{source_time}",
\t\t\t\t\t\t}},
\t\t\t\t\t\tInput = Input {{
\t\t\t\t\t\t\tSourceOp = "BurnLoader",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 0, 132 }} }},
\t\t\t\t}},
\t\t\t\tBurnScale = Transform {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tSize = Input {{
\t\t\t\t\t\t\tValue = 1,
\t\t\t\t\t\t\tExpression = "Params.NumberIn2",
\t\t\t\t\t\t}},
\t\t\t\t\t\tInput = Input {{
\t\t\t\t\t\t\tSourceOp = "BurnTime",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 55, 132 }} }},
\t\t\t\t}},
\t\t\t\tBurnSat = BrightnessContrast {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tSaturation = Input {{
\t\t\t\t\t\t\tValue = 1,
\t\t\t\t\t\t\tExpression = "Params.NumberIn3",
\t\t\t\t\t\t}},
\t\t\t\t\t\tInput = Input {{
\t\t\t\t\t\t\tSourceOp = "BurnScale",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 82, 132 }} }},
\t\t\t\t}},
\t\t\t\tBurnColor = ColorGain {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tGainRed = Input {{
\t\t\t\t\t\t\tValue = 1,
\t\t\t\t\t\t\tExpression = "Params.NumberIn4",
\t\t\t\t\t\t}},
\t\t\t\t\t\tGainGreen = Input {{
\t\t\t\t\t\t\tValue = 1,
\t\t\t\t\t\t\tExpression = "Params.NumberIn5",
\t\t\t\t\t\t}},
\t\t\t\t\t\tGainBlue = Input {{
\t\t\t\t\t\t\tValue = 1,
\t\t\t\t\t\t\tExpression = "Params.NumberIn6",
\t\t\t\t\t\t}},
\t\t\t\t\t\tInput = Input {{
\t\t\t\t\t\t\tSourceOp = "BurnSat",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 96, 132 }} }},
\t\t\t\t}},
\t\t\t\tBurnMerge = Merge {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tApplyMode = Input {{ Value = FuID {{ "Screen" }}, }},
\t\t\t\t\t\tBlend = Input {{
\t\t\t\t\t\t\tValue = 1,
\t\t\t\t\t\t\tExpression = "min(1, Params.NumberIn1)",
\t\t\t\t\t\t}},
\t\t\t\t\t\tPerformDepthMerge = Input {{ Value = 0, }},
\t\t\t\t\t\tBackground = Input {{
\t\t\t\t\t\t\tSourceOp = "Dissolve1",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t\tForeground = Input {{
\t\t\t\t\t\t\tSourceOp = "BurnColor",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 110, 33 }} }},
\t\t\t\t}}""",
    ])
    return macro(f"FilmBurn{display_index}", ("XfA", "Input"), ("XfB", "Input"),
                 "BurnMerge",
                 [("Params", "NumberIn1", "Burn Intensity", 1, 2),
                  ("Params", "NumberIn2", "Burn Size", 1, 3),
                  ("Params", "NumberIn3", "Burn Saturation", 1, 2),
                  ("Params", "NumberIn4", "Tint Red", 1, 2),
                  ("Params", "NumberIn5", "Tint Green", 1, 2),
                  ("Params", "NumberIn6", "Tint Blue", 1, 2)],
                 tools)


def rgb_split_slam_setting() -> str:
    """Metal: at the cut, the image shreds into R/G/B layers that fly apart
    horizontally and slam back together. Chromatic violence, zero OFX."""
    env = ENVELOPE  # 0->1->0 peaking at the cut
    # channel isolation enum values (ChannelBoolean): 5/6/7 = BG channel, 15 = Black
    def channel_iso(name, tor, tog, tob, pos):
        return f"""\
\t\t\t\t{name} = ChannelBoolean {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tToRed = Input {{ Value = {tor}, }},
\t\t\t\t\t\tToGreen = Input {{ Value = {tog}, }},
\t\t\t\t\t\tToBlue = Input {{ Value = {tob}, }},
\t\t\t\t\t\tToAlpha = Input {{ Value = 8, }},
\t\t\t\t\t\tBackground = Input {{ SourceOp = "Dissolve1", Source = "Output", }},
\t\t\t\t\t\tForeground = Input {{ SourceOp = "Dissolve1", Source = "Output", }},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {pos[0]}, {pos[1]} }} }},
\t\t\t\t}},"""

    shift = "Params.NumberIn3 * Params.NumberIn1 * 0.05"
    tools = "\n".join([
        params_tool([("Split Amount", 1), ("Blur Amount", 1)],
                    [("Envelope", env)]),
        transform("XfA", {"Size": "Input { Value = 1, }"}, (-220, 0)),
        transform("XfB", {"Size": "Input { Value = 1, }"}, (-220, 66)),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH, pos=(-110, 33)),
        channel_iso("IsoRed", 5, 15, 15, (0, 0)),
        channel_iso("IsoGreen", 15, 6, 15, (0, 33)),
        channel_iso("IsoBlue", 15, 15, 7, (0, 66)),
        transform("ShiftRed", {
            "Center": expr_input(f"Point(0.5 + {shift}, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (110, 0), source=("IsoRed", "Output")),
        transform("ShiftBlue", {
            "Center": expr_input(f"Point(0.5 - {shift}, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (110, 66), source=("IsoBlue", "Output")),
        f"""\
\t\t\t\tMergeRG = Merge {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tApplyMode = Input {{ Value = FuID {{ "Screen" }}, }},
\t\t\t\t\t\tPerformDepthMerge = Input {{ Value = 0, }},
\t\t\t\t\t\tBackground = Input {{ SourceOp = "IsoGreen", Source = "Output", }},
\t\t\t\t\t\tForeground = Input {{ SourceOp = "ShiftRed", Source = "Output", }},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 220, 33 }} }},
\t\t\t\t}},
\t\t\t\tMergeRGB = Merge {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tApplyMode = Input {{ Value = FuID {{ "Screen" }}, }},
\t\t\t\t\t\tPerformDepthMerge = Input {{ Value = 0, }},
\t\t\t\t\t\tBackground = Input {{ SourceOp = "MergeRG", Source = "Output", }},
\t\t\t\t\t\tForeground = Input {{ SourceOp = "ShiftBlue", Source = "Output", }},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 330, 33 }} }},
\t\t\t\t}},""",
        blur("PostBlur", "MergeRGB",
             "Params.NumberIn3 * 6 * Params.NumberIn2", pos=(440, 33), last=True),
    ])
    return macro("RGBSplitSlam", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Split Amount", 1, 3),
                  ("Params", "NumberIn2", "Blur Amount", 1, 2)],
                 tools)


def shake_slam_setting() -> str:
    """Metal: B-side lands with a decaying impact shake — like the cut hit a
    downbeat. Deterministic pseudo-random jolt from stacked sines (expression
    grammar has sin(); no randomness needed, and it renders identically
    every time)."""
    # decaying shake, second half only: amplitude (1-p2)^2 where p2 = progress in 2nd half
    p2 = f"(2*({T})-1)"  # 0..1 across second half
    amp = f"Params.NumberIn1 * 0.03 * ((1-{p2})^2)"
    shake_x = f"iif({T} < 0.5, 0.5, 0.5 + {amp} * sin({p2}*47))"
    shake_y = f"iif({T} < 0.5, 0.5, 0.5 + {amp} * 0.6 * sin({p2}*31+2))"
    # A-side: quick push-in before the cut
    size_a = f"iif({T} < 0.5, 1 + 0.12 * {EASE_IN_CUBIC_FIRST_HALF}, 1.12)"
    size_b = f"iif({T} < 0.5, 1.05, 1.05 - 0.05 * {p2})"

    tools = "\n".join([
        params_tool([("Shake Amount", 1), ("Blur Amount", 1)],
                    [("Envelope", ENVELOPE)]),
        transform("XfA", {
            "Size": expr_input(size_a, 1),
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 0)),
        transform("XfB", {
            "Center": expr_input(f"Point({shake_x}, {shake_y})", "{ 0.5, 0.5 }"),
            "Size": expr_input(size_b, 1),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 66)),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH),
        blur("PostBlur", "Dissolve1",
             "Params.NumberIn3 * 8 * Params.NumberIn2", pos=(110, 33), last=True),
    ])
    return macro("ShakeSlam", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Shake Amount", 1, 3),
                  ("Params", "NumberIn2", "Blur Amount", 1, 2)],
                 tools)


def crush_zoom_setting() -> str:
    """Metal/urban: violent zoom-through — A-side zooms IN hard while
    rotating, B-side arrives zoomed WAY out and crash-lands to rest.
    More brutal than Zoom Punch: bigger travel, opposing rotation."""
    zoom_a = f"iif({T} < 0.5, 1 + 1.5 * Params.NumberIn1 * {EASE_IN_CUBIC_FIRST_HALF}, 2.5)"
    angle_a = f"iif({T} < 0.5, 8 * Params.NumberIn1 * {EASE_IN_CUBIC_FIRST_HALF}, 8)"
    zoom_b = f"iif({T} < 0.5, 0.4, 1 - 0.6 * {EASE_OUT_CUBIC_SECOND_HALF})"
    angle_b = f"iif({T} < 0.5, -8, -8 * {EASE_OUT_CUBIC_SECOND_HALF})"

    tools = "\n".join([
        params_tool([("Intensity", 1), ("Blur Amount", 1)],
                    [("Envelope", ENVELOPE)]),
        transform("XfA", {
            "Size": expr_input(zoom_a, 1),
            "Angle": expr_input(angle_a),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 0)),
        transform("XfB", {
            "Size": expr_input(zoom_b, 1),
            "Angle": expr_input(angle_b),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (-110, 66)),
        dissolve("Dissolve1", "XfA", "XfB", HARD_SWITCH),
        blur("PostBlur", "Dissolve1",
             "Params.NumberIn3 * 16 * Params.NumberIn2",
             "Params.NumberIn3 * 16 * Params.NumberIn2", pos=(110, 33), last=True),
    ])
    return macro("CrushZoom", ("XfA", "Input"), ("XfB", "Input"), "PostBlur",
                 [("Params", "NumberIn1", "Intensity", 1, 2),
                  ("Params", "NumberIn2", "Blur Amount", 1, 2)],
                 tools)


# Registry: display name -> generator callable
TRANSITIONS: dict = {
    "Zoom Punch": zoom_punch_setting,
    "Spin Punch": spin_punch_setting,
    "Whip Pan Left": lambda: whip_pan_setting("Left"),
    "Whip Pan Right": lambda: whip_pan_setting("Right"),
    "Whip Pan Up": lambda: whip_pan_setting("Up"),
    "Whip Pan Down": lambda: whip_pan_setting("Down"),
    "Flash Cut": flash_cut_setting,
    "RGB Split Slam": rgb_split_slam_setting,
    "Shake Slam": shake_slam_setting,
    "Crush Zoom": crush_zoom_setting,
}
for _i, (_folder, _first, _frames) in enumerate(BURNS, start=1):
    TRANSITIONS[f"Film Burn {_i}"] = (
        lambda f=_folder, ff=_first, n=_frames, i=_i: film_burn_setting(f, ff, n, i)
    )


def build_drfx(out_dir: str = DIST) -> str:
    os.makedirs(out_dir, exist_ok=True)
    drfx_path = os.path.join(out_dir, f"{PACK_NAME}.drfx")
    with zipfile.ZipFile(drfx_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, generate in TRANSITIONS.items():
            arcname = f"Edit/Transitions/{PACK_NAME}/{name}.setting"
            zf.writestr(arcname, generate())
    return drfx_path


def templates_dir() -> str:
    return os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true",
                        help="copy the built .drfx into Resolve's user Templates dir")
    args = parser.parse_args()

    missing = [f for f, _, _ in
               ((os.path.join(BURN_SEQ_DIR, d, ff), d, n) for d, ff, n in BURNS)
               if not os.path.exists(f)]
    if missing:
        print(f"WARNING: burn sequences missing: {missing}", file=sys.stderr)
        print("Film Burn transitions will not render until they exist.", file=sys.stderr)

    path = build_drfx()
    print(f"built: {path}")
    for name in TRANSITIONS:
        print(f"  - {name}")

    if args.install:
        import shutil

        dest = os.path.join(templates_dir(), os.path.basename(path))
        shutil.copy2(path, dest)
        print(f"installed: {dest}")
        print("Restart Resolve, then look in Effects Library > Video Transitions "
              f"> Fusion Transitions > {PACK_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
