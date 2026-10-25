#!/usr/bin/env python3
"""Generate DaVinci Resolve Edit-page Fusion EFFECTS (.setting) and pack them
into an installable .drfx archive.

Same serialization spec as drfx/make_pack.py (transitions), with one key
difference: an Edit-page effect is a MacroOperator with ONLY MainInput1 (the
clip it is dropped onto) plus MainOutput1 — no MainInput2 — and it lives under
Edit/Effects/<Pack>/ inside the zip. Everything else (hand-built Lua tables,
tab indentation, Params Custom tool with LUT boilerplate, InstanceInputs for
Inspector controls, ordered() blocks, unique tool names) is identical.

Ground truth (live Resolve 21 SaveSettings probes of EllipseMask,
RectangleMask, FastNoise, ChannelBoolean, BrightnessContrast, SoftGlow,
Merge, Transform):

- Masks connect to a tool's EffectMask input via
  `EffectMask = Input { SourceOp = "<mask>", Source = "Mask" }`.
- Mask tools serialize Filter as `FuID { "Fast Gaussian" }` and
  `ClippingMode = FuID { "None" }`; with UseFrameFormatSettings = 1 the
  MaskWidth/MaskHeight/PixelAspect fields are comp-derived, so templates
  omit them to stay resolution-independent.
- ChannelBoolean channel selects (ToRed/ToGreen/ToBlue/ToAlpha) serialize as
  plain 0-based combo integers: 0=Red FG, 1=Green FG, 2=Blue FG, 3=Alpha FG,
  4=Do Nothing, 5=Red BG, 6=Green BG, 7=Blue BG, 8=Alpha BG, 15=Black,
  16=White, 17=Mid Grey (probed via INPST_ComboControl_String).
- FastNoise has a SeetheRate input (0..1) that animates the noise per-frame
  with no keyframes or expressions — preferred over a `time` expression.
- Effects are static: no time/comp.RenderEnd expressions anywhere (the only
  sanctioned animation is FastNoise's SeetheRate, which is not an expression).

Usage:
    python3 drfx/make_effects.py                 # build dist/<pack>.drfx
    python3 drfx/make_effects.py --install       # build + copy into Resolve Templates
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

PACK_NAME = "mvarge FX"
DIST = os.path.join(os.path.dirname(__file__), "..", "dist")

LUT_COLORS = [(204, 0, 0), (0, 204, 0), (0, 0, 204), (180, 180, 180)]

# ChannelBoolean combo values (0-based, from live probe)
CB_RED_BG = 5
CB_GREEN_BG = 6
CB_BLUE_BG = 7
CB_ALPHA_BG = 8
CB_BLACK = 15


# ---------------------------------------------------------------------------
# Emission helpers (adapted from make_pack.py; kept self-contained on purpose)
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


def params_tool(numbers: list[tuple[str, float]]) -> str:
    """A Custom tool named Params exposing tunable numbers.

    numbers — (label, default) pairs mapped to NumberIn1..N (user-tunable).
    """
    lines = []
    idx = 0
    for label, default in numbers:
        idx += 1
        lines.append(f'\t\t\t\t\t\tNumberIn{idx} = Input {{ Value = {default}, }},')
    for i, (label, _) in enumerate(numbers, start=1):
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


def macro(name: str, main_in: tuple[str, str], output_op: str,
          controls: list[tuple], tools_lua: str) -> str:
    """Assemble a complete effect .setting.

    Unlike a transition, an effect has only MainInput1 (no MainInput2)."""
    inputs = [
        f'\t\t\t\tComments = Input {{ Value = "{PACK_NAME} — generated by drfx/make_effects.py", }},',
        f'\t\t\t\tMainInput1 = InstanceInput {{\n\t\t\t\t\tSourceOp = "{main_in[0]}",\n\t\t\t\t\tSource = "{main_in[1]}",\n\t\t\t\t}},',
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


def tool(name: str, tool_type: str, inputs: dict[str, str],
         pos: tuple[int, int], last: bool = False) -> str:
    """Generic stock-tool emitter: inputs is an ordered {id: rhs} dict where
    rhs is a complete `Input { ... }` (or bare value) Lua fragment."""
    lines = [f"\t\t\t\t\t\t{k} = {v}," for k, v in inputs.items()]
    body = "\n".join(lines)
    comma = "" if last else ","
    return f"""\
\t\t\t\t{name} = {tool_type} {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
{body}
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ {pos[0]}, {pos[1]} }} }},
\t\t\t\t}}{comma}"""


def src_input(op: str, source: str = "Output") -> str:
    return f'Input {{\n\t\t\t\t\t\t\tSourceOp = "{op}",\n\t\t\t\t\t\t\tSource = "{source}",\n\t\t\t\t\t\t}}'


def expr_input(expr: str, value: object = 0) -> str:
    return f'Input {{ Value = {value}, Expression = "{expr}" }}'


# ---------------------------------------------------------------------------
# Effect generators
# ---------------------------------------------------------------------------

def vignette_setting() -> str:
    """Inverted soft ellipse masking a gain-down BrightnessContrast: classic
    darkened-corners vignette. Amount maps to Gain = 1 - Amount*0.6."""
    tools = "\n".join([
        params_tool([("Amount", 0.4)]),
        tool("VignetteMask", "EllipseMask", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "SoftEdge": "Input { Value = 0.5, }",
            "Invert": "Input { Value = 1, }",
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "ClippingMode": 'Input { Value = FuID { "None" }, }',
            "Width": "Input { Value = 1, }",
            "Height": expr_input("VignetteMask.Width", 1),
        }, (-110, 33)),
        tool("Darken", "BrightnessContrast", {
            "Gain": expr_input("1 - Params.NumberIn1 * 0.6", 1),
            "EffectMask": src_input("VignetteMask", "Mask"),
        }, (0, 0), last=True),
    ])
    return macro("Vignette", ("Darken", "Input"), "Darken",
                 [("Params", "NumberIn1", "Amount", 0.4, 1),
                  ("VignetteMask", "SoftEdge", "Softness", 0.5, 1),
                  ("VignetteMask", "Width", "Size", 1, 2)],
                 tools)


def letterbox_setting() -> str:
    """Cinemascope bars: an inverted hard rectangle masks a Gain=0
    BrightnessContrast, blacking out everything outside the 2.39:1 window.
    On 16:9, content height = (16/9)/2.39 = 0.744, so each bar is 0.128."""
    tools = "\n".join([
        params_tool([("Bar Height", 0.128)]),
        tool("BarsMask", "RectangleMask", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "SoftEdge": "Input { Value = 0, }",
            "Invert": "Input { Value = 1, }",
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "ClippingMode": 'Input { Value = FuID { "None" }, }',
            "Width": "Input { Value = 1, }",
            "Height": expr_input("1 - 2 * Params.NumberIn1", 0.744),
        }, (-110, 33)),
        tool("Bars", "BrightnessContrast", {
            "Gain": "Input { Value = 0, }",
            "Blend": "Input { Value = 1, }",
            "EffectMask": src_input("BarsMask", "Mask"),
        }, (0, 0), last=True),
    ])
    return macro("Letterbox239", ("Bars", "Input"), "Bars",
                 [("Params", "NumberIn1", "Aspect (Bar Height)", 0.128, 0.5),
                  ("Bars", "Blend", "Opacity", 1, 1)],
                 tools)


def film_grain_setting() -> str:
    """Animated FastNoise soft-lit over the clip at low blend. SeetheRate = 1
    reseeds the noise every frame with no keyframes or time expressions.
    Grain Size 1 = fine (XScale 40); larger = coarser."""
    tools = "\n".join([
        params_tool([("Grain Amount", 0.15), ("Grain Size", 1)]),
        tool("GrainNoise", "FastNoise", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "Detail": "Input { Value = 10, }",
            "Contrast": "Input { Value = 1.5, }",
            "SeetheRate": "Input { Value = 1, }",
            "XScale": expr_input("40 / max(0.25, Params.NumberIn2)", 40),
        }, (-110, 33)),
        tool("GrainMerge", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "SoftLight" }, }',
            "Blend": expr_input("Params.NumberIn1", 0.15),
            "PerformDepthMerge": "Input { Value = 0, }",
            "Foreground": src_input("GrainNoise"),
        }, (0, 0), last=True),
    ])
    return macro("FilmGrain", ("GrainMerge", "Background"), "GrainMerge",
                 [("Params", "NumberIn1", "Grain Amount", 0.15, 0.4),
                  ("Params", "NumberIn2", "Grain Size", 1, 4)],
                 tools)


def chromatic_aberration_setting() -> str:
    """RGB split: three ChannelBooleans isolate R/G/B from the input (BG
    channel selects, others Black), red and blue shift horizontally in
    opposite directions, and two Screen merges recombine — Screen of
    disjoint channels is lossless recombination."""
    def channel_iso(name: str, to_red: int, to_green: int, to_blue: int,
                    pos: tuple[int, int]) -> str:
        return tool(name, "ChannelBoolean", {
            "ToRed": f"Input {{ Value = {to_red}, }}",
            "ToGreen": f"Input {{ Value = {to_green}, }}",
            "ToBlue": f"Input {{ Value = {to_blue}, }}",
            "ToAlpha": f"Input {{ Value = {CB_ALPHA_BG}, }}",
            "Background": src_input("Src"),
            "Foreground": src_input("Src"),
        }, pos)

    tools = "\n".join([
        params_tool([("Shift Amount", 0.005)]),
        tool("Src", "Transform", {
            "Size": "Input { Value = 1, }",
        }, (-220, 33)),
        channel_iso("IsoRed", CB_RED_BG, CB_BLACK, CB_BLACK, (-110, 0)),
        channel_iso("IsoGreen", CB_BLACK, CB_GREEN_BG, CB_BLACK, (-110, 33)),
        channel_iso("IsoBlue", CB_BLACK, CB_BLACK, CB_BLUE_BG, (-110, 66)),
        tool("ShiftRed", "Transform", {
            "Center": expr_input("Point(0.5 + Params.NumberIn1, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("IsoRed"),
        }, (0, 0)),
        tool("ShiftBlue", "Transform", {
            "Center": expr_input("Point(0.5 - Params.NumberIn1, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("IsoBlue"),
        }, (0, 66)),
        tool("MergeRG", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("IsoGreen"),
            "Foreground": src_input("ShiftRed"),
        }, (110, 33)),
        tool("MergeRGB", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("MergeRG"),
            "Foreground": src_input("ShiftBlue"),
        }, (220, 33), last=True),
    ])
    return macro("ChromaticAberration", ("Src", "Input"), "MergeRGB",
                 [("Params", "NumberIn1", "Shift Amount", 0.005, 0.02)],
                 tools)


def punch_glow_setting() -> str:
    """Straight SoftGlow with the three musical knobs exposed."""
    tools = tool("Glow", "SoftGlow", {
        "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
        "Gain": "Input { Value = 3, }",
        "Threshold": "Input { Value = 0.6, }",
        "Blend": "Input { Value = 1, }",
    }, (0, 0), last=True)
    return macro("PunchGlow", ("Glow", "Input"), "Glow",
                 [("Glow", "Gain", "Glow Amount", 3, 8),
                  ("Glow", "Threshold", "Threshold", 0.6, 1),
                  ("Glow", "Blend", "Blend", 1, 1)],
                 tools)


def turbulent_displace_setting() -> str:
    """Organic warp: animated FastNoise drives a Displace on the image —
    heat-haze / possessed-footage wobble. Speed via FastNoise SeetheRate,
    scale via noise detail, strength via Displace refraction."""
    tools = "\n".join([
        params_tool([("Strength", 0.15), ("Scale", 6), ("Speed", 1)]),
        tool("Src", "Transform", {
            "Size": "Input { Value = 1, }",
        }, (-220, 33)),
        tool("WarpNoise", "FastNoise", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "Detail": expr_input("Params.NumberIn2", 6),
            "Contrast": "Input { Value = 1.2, }",
            "SeetheRate": expr_input("0.1 * Params.NumberIn3", 0.1),
            "XScale": "Input { Value = 4, }",
        }, (-110, 66)),
        tool("Warp", "Displace", {
            "Type": "Input { Value = 1, }",
            "XRefraction": expr_input("Params.NumberIn1", 0.15),
            "YRefraction": expr_input("Params.NumberIn1", 0.15),
            "Input": src_input("Src"),
            "Foreground": src_input("WarpNoise"),
        }, (0, 33), last=True),
    ])
    return macro("TurbulentDisplace", ("Src", "Input"), "Warp",
                 [("Params", "NumberIn1", "Strength", 0.15, 0.5),
                  ("Params", "NumberIn2", "Scale", 6, 12),
                  ("Params", "NumberIn3", "Speed", 1, 4)],
                 tools)


def posterize_time_setting() -> str:
    """Choppy stop-motion feel: TimeStretcher quantizes source time to every
    Nth frame. Rate control = frames held per step."""
    tools = "\n".join([
        params_tool([("Hold Frames", 3)]),
        tool("Src", "Transform", {
            "Size": "Input { Value = 1, }",
        }, (-110, 0)),
        f"""\
\t\t\t\tStepTime = TimeStretcher {{
\t\t\t\t\tCtrlWShown = false,
\t\t\t\t\tInputs = {{
\t\t\t\t\t\tSourceTime = Input {{
\t\t\t\t\t\t\tValue = 0,
\t\t\t\t\t\t\tExpression = "floor(time / max(1, Params.NumberIn1)) * max(1, Params.NumberIn1)",
\t\t\t\t\t\t}},
\t\t\t\t\t\tInput = Input {{
\t\t\t\t\t\t\tSourceOp = "Src",
\t\t\t\t\t\t\tSource = "Output",
\t\t\t\t\t\t}},
\t\t\t\t\t}},
\t\t\t\t\tViewInfo = OperatorInfo {{ Pos = {{ 0, 0 }} }},
\t\t\t\t}}""",
    ])
    return macro("PosterizeTime", ("Src", "Input"), "StepTime",
                 [("Params", "NumberIn1", "Hold Frames", 3, 12)],
                 tools)


def pump_setting() -> str:
    """Rhythmic zoom pump: sine-driven scale bump for beat-synced sections.
    Tune Pump Rate to your BPM (rate = beats per second at 25fps baseline)."""
    # sine period in frames: fps/rate; using time directly — editors trim
    # the clip so phase aligns with the beat.
    size = "1 + Params.NumberIn1 * 0.5 * (0.5 + 0.5 * sin(time * 6.2832 * Params.NumberIn2 / 25))"
    tools = "\n".join([
        params_tool([("Pump Amount", 0.08), ("Pump Rate", 2)]),
        tool("Pump", "Transform", {
            "Size": expr_input(size, 1),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
        }, (0, 0), last=True),
    ])
    return macro("BeatPump", ("Pump", "Input"), "Pump",
                 [("Params", "NumberIn1", "Pump Amount", 0.08, 0.3),
                  ("Params", "NumberIn2", "Pump Rate", 2, 8)],
                 tools)


# ---------------------------------------------------------------------------
# "AE look" tier — recreations of popular After Effects / plugin looks with
# stock Fusion tools only. Expression grammar used: + - * / ^, sin, floor,
# max, min, abs, iif, time. Pseudo-randomness comes from the classic sine
# hash (x - floor(x) is frac; there is no frac()/mod in SimpleExpression), so
# every effect renders identically on every pass — no flickering re-renders.
# ---------------------------------------------------------------------------

def _hash(n: str) -> str:
    """Deterministic 0..1 pseudo-random value for expression `n`."""
    s = f"(sin(({n}) * 12.9898) * 43758.5453)"
    return f"({s} - floor({s}))"


def _beat_phase(bpm: str, fps: str, offset: str = "0") -> str:
    """0..1 sawtooth that restarts on every beat."""
    beats = f"((time + {offset}) * {bpm} / (60 * max(1, {fps})))"
    return f"({beats} - floor({beats}))"


def glitch_setting() -> str:
    """Digital glitch (AE 'Glitchify' / Data Glitch style): random bursts in
    which horizontal bands of the picture tear sideways and the RGB channels
    split. Bursts are chosen per block of `Hold Frames` frames by a sine hash,
    so the effect is choppy-random but renders deterministically.

    Chain: Src -> band Displace (driven by stretched, discontinuous noise =
    horizontal tear bands) -> channel split (R/B shifted opposite ways) ->
    Screen recombine."""
    hold = "max(1, Params.NumberIn3)"
    block = f"floor(time / {hold})"
    gate = f"iif({_hash(block)} > 1 - Params.NumberIn2, 1, 0)"
    # signed jitter so the RGB split swaps direction between bursts
    jitter = f"({_hash(block + ' + 7.31')} - 0.5) * 2"

    def channel_iso(name, r, g, b, pos):
        return tool(name, "ChannelBoolean", {
            "ToRed": f"Input {{ Value = {r}, }}",
            "ToGreen": f"Input {{ Value = {g}, }}",
            "ToBlue": f"Input {{ Value = {b}, }}",
            "ToAlpha": f"Input {{ Value = {CB_ALPHA_BG}, }}",
            "Background": src_input("Tear"),
            "Foreground": src_input("Tear"),
        }, pos)

    shift = f"Params.NumberIn1 * 0.02 * {gate} * {jitter}"
    tools = "\n".join([
        params_tool([("Intensity", 1), ("Glitch Density", 0.35),
                     ("Hold Frames", 2), ("Band Size", 1)]),
        tool("Src", "Transform", {"Size": "Input { Value = 1, }"}, (-330, 33)),
        tool("BandNoise", "FastNoise", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "Discontinuous": "Input { Value = 1, }",
            "Detail": "Input { Value = 1, }",
            "Contrast": "Input { Value = 4, }",
            "LockXY": "Input { Value = 0, }",
            "XScale": "Input { Value = 0.5, }",
            "YScale": expr_input("30 / max(0.25, Params.NumberIn4)", 30),
            "SeetheRate": "Input { Value = 1, }",
        }, (-330, 99)),
        tool("Tear", "Displace", {
            "Type": "Input { Value = 1, }",
            "XRefraction": expr_input(f"Params.NumberIn1 * 0.08 * {gate}", 0),
            "YRefraction": "Input { Value = 0, }",
            "Input": src_input("Src"),
            "Foreground": src_input("BandNoise"),
        }, (-220, 33)),
        channel_iso("IsoRed", CB_RED_BG, CB_BLACK, CB_BLACK, (-110, 0)),
        channel_iso("IsoGreen", CB_BLACK, CB_GREEN_BG, CB_BLACK, (-110, 33)),
        channel_iso("IsoBlue", CB_BLACK, CB_BLACK, CB_BLUE_BG, (-110, 66)),
        tool("ShiftRed", "Transform", {
            "Center": expr_input(f"Point(0.5 + {shift}, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("IsoRed"),
        }, (0, 0)),
        tool("ShiftBlue", "Transform", {
            "Center": expr_input(f"Point(0.5 - {shift}, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("IsoBlue"),
        }, (0, 66)),
        tool("MergeRG", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("IsoGreen"),
            "Foreground": src_input("ShiftRed"),
        }, (110, 33)),
        tool("MergeRGB", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("MergeRG"),
            "Foreground": src_input("ShiftBlue"),
        }, (220, 33), last=True),
    ])
    return macro("Glitch", ("Src", "Input"), "MergeRGB",
                 [("Params", "NumberIn1", "Intensity", 1, 3),
                  ("Params", "NumberIn2", "Glitch Density", 0.35, 1),
                  ("Params", "NumberIn3", "Hold Frames", 2, 12),
                  ("Params", "NumberIn4", "Band Size", 1, 4)],
                 tools)


def vhs_setting() -> str:
    """VHS / camcorder tape look: tracking wobble (fine horizontal jitter
    from thin animated noise bands), chroma smear (horizontal-only blur),
    slight colour fringing, lifted blacks + washed saturation, and soft tape
    noise on top."""
    tools = "\n".join([
        params_tool([("Amount", 1), ("Wobble", 1), ("Noise", 0.25)]),
        tool("Src", "Transform", {"Size": "Input { Value = 1, }"}, (-330, 33)),
        tool("TrackNoise", "FastNoise", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "Detail": "Input { Value = 2, }",
            "Contrast": "Input { Value = 1.5, }",
            "LockXY": "Input { Value = 0, }",
            "XScale": "Input { Value = 0.3, }",
            "YScale": "Input { Value = 60, }",
            "SeetheRate": "Input { Value = 0.6, }",
        }, (-330, 99)),
        tool("Wobble", "Displace", {
            "Type": "Input { Value = 1, }",
            "XRefraction": expr_input("Params.NumberIn2 * 0.012", 0.012),
            "YRefraction": "Input { Value = 0, }",
            "Input": src_input("Src"),
            "Foreground": src_input("TrackNoise"),
        }, (-220, 33)),
        tool("Smear", "Blur", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "LockXY": "Input { Value = 0, }",
            "XBlurSize": expr_input("2.5 * Params.NumberIn1", 2.5),
            "YBlurSize": "Input { Value = 0, }",
            "Input": src_input("Wobble"),
        }, (-110, 33)),
        tool("Fringe", "Transform", {
            "Center": expr_input("Point(0.5 + 0.002 * Params.NumberIn1, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("Smear"),
        }, (-110, 66)),
        tool("FringeMix", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "Blend": expr_input("0.25 * Params.NumberIn1", 0.25),
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("Smear"),
            "Foreground": src_input("Fringe"),
        }, (0, 33)),
        tool("TapeGrade", "BrightnessContrast", {
            "Lift": expr_input("0.06 * Params.NumberIn1", 0.06),
            "Gain": expr_input("1 - 0.08 * Params.NumberIn1", 0.92),
            "Saturation": expr_input("1 - 0.3 * Params.NumberIn1", 0.7),
            "Input": src_input("FringeMix"),
        }, (110, 33)),
        tool("TapeNoise", "FastNoise", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "Detail": "Input { Value = 10, }",
            "Contrast": "Input { Value = 2, }",
            "XScale": "Input { Value = 60, }",
            "SeetheRate": "Input { Value = 1, }",
        }, (110, 99)),
        tool("NoiseMix", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "SoftLight" }, }',
            "Blend": expr_input("Params.NumberIn3", 0.25),
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("TapeGrade"),
            "Foreground": src_input("TapeNoise"),
        }, (220, 33), last=True),
    ])
    return macro("VHS", ("Src", "Input"), "NoiseMix",
                 [("Params", "NumberIn1", "Amount", 1, 2),
                  ("Params", "NumberIn2", "Tracking Wobble", 1, 4),
                  ("Params", "NumberIn3", "Tape Noise", 0.25, 1)],
                 tools)


def beat_strobe_setting() -> str:
    """Beat-synced strobe: a flash on every beat at the given BPM that decays
    over `Decay` of the beat. Mode 0 = flash to white (exposure punch),
    1 = blackout strobe. Beat Offset (frames) nudges the phase onto the
    downbeat once the clip is placed."""
    phase = _beat_phase("Params.NumberIn1", "Params.NumberIn5", "Params.NumberIn6")
    pulse = f"max(0, 1 - {phase} / max(0.01, Params.NumberIn3))"
    hit = f"Params.NumberIn2 * {pulse}"
    gain = f"iif(Params.NumberIn4 > 0.5, 1 - {hit}, 1 + 2 * {hit})"
    lift = f"iif(Params.NumberIn4 > 0.5, 0, 0.3 * {hit})"
    tools = "\n".join([
        params_tool([("BPM", 120), ("Intensity", 0.8), ("Decay", 0.3),
                     ("Blackout Mode", 0), ("FPS", 25), ("Beat Offset", 0)]),
        tool("Strobe", "BrightnessContrast", {
            "Gain": expr_input(gain, 1),
            "Lift": expr_input(lift, 0),
        }, (0, 0), last=True),
    ])
    return macro("BeatStrobe", ("Strobe", "Input"), "Strobe",
                 [("Params", "NumberIn1", "BPM", 120, 240),
                  ("Params", "NumberIn2", "Intensity", 0.8, 1),
                  ("Params", "NumberIn3", "Decay", 0.3, 1),
                  ("Params", "NumberIn4", "Blackout Mode (0/1)", 0, 1),
                  ("Params", "NumberIn5", "Timeline FPS", 25, 60),
                  ("Params", "NumberIn6", "Beat Offset (frames)", 0, 60)],
                 tools)


def handheld_shake_setting() -> str:
    """Handheld / camera shake (AE 'Wiggle' expression): smooth organic drift
    from stacked incommensurate sines on X, Y and rotation, with a matching
    zoom so the frame edges never show. Speed 1 = gentle handheld, 4+ =
    earthquake."""
    t = "(time * Params.NumberIn2)"
    amp = "Params.NumberIn1 * 0.01"
    x = f"0.5 + {amp} * (sin({t} * 0.31) + 0.5 * sin({t} * 0.73 + 1.7) + 0.25 * sin({t} * 1.91 + 4.1))"
    y = f"0.5 + {amp} * (sin({t} * 0.27 + 2.3) + 0.5 * sin({t} * 0.81 + 0.6) + 0.25 * sin({t} * 2.07 + 3.3))"
    ang = f"Params.NumberIn3 * Params.NumberIn1 * (sin({t} * 0.23 + 0.9) + 0.4 * sin({t} * 0.97 + 2.2))"
    tools = "\n".join([
        params_tool([("Amount", 1), ("Speed", 1), ("Rotation", 0.5)]),
        tool("Shake", "Transform", {
            "Center": expr_input(f"Point({x}, {y})", "{ 0.5, 0.5 }"),
            "Angle": expr_input(ang, 0),
            "Size": expr_input("1 + Params.NumberIn1 * 0.04", 1.04),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 180, }",
        }, (0, 0), last=True),
    ])
    return macro("HandheldShake", ("Shake", "Input"), "Shake",
                 [("Params", "NumberIn1", "Amount", 1, 5),
                  ("Params", "NumberIn2", "Speed", 1, 6),
                  ("Params", "NumberIn3", "Rotation", 0.5, 3)],
                 tools)


def light_leak_setting() -> str:
    """Procedural light leak: a big, soft, slowly drifting noise blob tinted
    warm (default orange/red) and screened over the clip — the classic film
    light-leak / lens-flare-wash overlay, no stock footage needed. Tint is a
    ColorGain (the BrightnessContrast RGB inputs are offsets, not gains)."""
    t = "(time * Params.NumberIn2)"
    tools = "\n".join([
        params_tool([("Amount", 0.6), ("Drift Speed", 1), ("Red", 1.0),
                     ("Green", 0.45), ("Blue", 0.15)]),
        tool("Src", "Transform", {"Size": "Input { Value = 1, }"}, (-220, 33)),
        tool("LeakNoise", "FastNoise", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "Detail": "Input { Value = 1, }",
            "Contrast": "Input { Value = 2.5, }",
            "Brightness": "Input { Value = -0.25, }",
            "XScale": "Input { Value = 1.2, }",
            "SeetheRate": expr_input("0.02 * Params.NumberIn2", 0.02),
        }, (-220, 99)),
        tool("LeakDrift", "Transform", {
            "Center": expr_input(
                f"Point(0.5 + 0.25 * sin({t} * 0.021), 0.5 + 0.15 * sin({t} * 0.017 + 1.3))",
                "{ 0.5, 0.5 }"),
            "Size": "Input { Value = 1.6, }",
            "Edges": "Input { Value = 3, }",
            "Input": src_input("LeakNoise"),
        }, (-110, 99)),
        tool("LeakSoft", "Blur", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "XBlurSize": "Input { Value = 40, }",
            "Input": src_input("LeakDrift"),
        }, (0, 99)),
        tool("LeakTint", "ColorGain", {
            "GainRed": expr_input("Params.NumberIn3", 1),
            "GainGreen": expr_input("Params.NumberIn4", 0.45),
            "GainBlue": expr_input("Params.NumberIn5", 0.15),
            "Input": src_input("LeakSoft"),
        }, (110, 99)),
        tool("LeakMerge", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "Blend": expr_input("Params.NumberIn1", 0.6),
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("Src"),
            "Foreground": src_input("LeakTint"),
        }, (110, 33), last=True),
    ])
    return macro("LightLeak", ("Src", "Input"), "LeakMerge",
                 [("Params", "NumberIn1", "Amount", 0.6, 1),
                  ("Params", "NumberIn2", "Drift Speed", 1, 5),
                  ("Params", "NumberIn3", "Tint Red", 1.0, 2),
                  ("Params", "NumberIn4", "Tint Green", 0.45, 2),
                  ("Params", "NumberIn5", "Tint Blue", 0.15, 2)],
                 tools)


def neon_edges_setting() -> str:
    """Saber-style neon outline on footage: edge detect (image minus its blur,
    via a Difference merge), boost + tint the edges, glow them, then screen
    them over a darkened copy of the clip. Great on silhouettes / guitar
    necks / stage lights. Darken = how much the underlying clip is crushed."""
    tools = "\n".join([
        params_tool([("Edge Strength", 6), ("Glow", 4), ("Darken", 0.6),
                     ("Red", 0.2), ("Green", 0.6), ("Blue", 1.0)]),
        tool("Src", "Transform", {"Size": "Input { Value = 1, }"}, (-330, 33)),
        tool("EdgeBlur", "Blur", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "XBlurSize": "Input { Value = 3, }",
            "Input": src_input("Src"),
        }, (-220, 99)),
        tool("Edges", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Difference" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("Src"),
            "Foreground": src_input("EdgeBlur"),
        }, (-110, 99)),
        tool("EdgeBoost", "BrightnessContrast", {
            "Gain": expr_input("Params.NumberIn1", 6),
            "Saturation": "Input { Value = 0, }",
            "Input": src_input("Edges"),
        }, (0, 99)),
        tool("EdgeTint", "ColorGain", {
            "GainRed": expr_input("Params.NumberIn4", 0.2),
            "GainGreen": expr_input("Params.NumberIn5", 0.6),
            "GainBlue": expr_input("Params.NumberIn6", 1.0),
            "Input": src_input("EdgeBoost"),
        }, (110, 99)),
        tool("EdgeGlow", "SoftGlow", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "Gain": expr_input("Params.NumberIn2", 4),
            "Threshold": "Input { Value = 0.05, }",
            "Input": src_input("EdgeTint"),
        }, (220, 99)),
        tool("Crush", "BrightnessContrast", {
            "Gain": expr_input("1 - Params.NumberIn3", 0.4),
            "Input": src_input("Src"),
        }, (110, 33)),
        tool("NeonMerge", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("Crush"),
            "Foreground": src_input("EdgeGlow"),
        }, (330, 33), last=True),
    ])
    return macro("NeonEdges", ("Src", "Input"), "NeonMerge",
                 [("Params", "NumberIn1", "Edge Strength", 6, 20),
                  ("Params", "NumberIn2", "Glow", 4, 10),
                  ("Params", "NumberIn3", "Darken Clip", 0.6, 1),
                  ("Params", "NumberIn4", "Neon Red", 0.2, 2),
                  ("Params", "NumberIn5", "Neon Green", 0.6, 2),
                  ("Params", "NumberIn6", "Neon Blue", 1.0, 2)],
                 tools)


# Registry: display name -> generator callable
EFFECTS: dict = {
    "Vignette": vignette_setting,
    "Letterbox 2.39": letterbox_setting,
    "Film Grain": film_grain_setting,
    "Chromatic Aberration": chromatic_aberration_setting,
    "Punch Glow": punch_glow_setting,
    "Turbulent Displace": turbulent_displace_setting,
    "Posterize Time": posterize_time_setting,
    "Beat Pump": pump_setting,
    "Glitch": glitch_setting,
    "VHS": vhs_setting,
    "Beat Strobe": beat_strobe_setting,
    "Handheld Shake": handheld_shake_setting,
    "Light Leak": light_leak_setting,
    "Neon Edges": neon_edges_setting,
}


def build_drfx(out_dir: str = DIST) -> str:
    os.makedirs(out_dir, exist_ok=True)
    drfx_path = os.path.join(out_dir, f"{PACK_NAME}.drfx")
    with zipfile.ZipFile(drfx_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, generate in EFFECTS.items():
            arcname = f"Edit/Effects/{PACK_NAME}/{name}.setting"
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

    path = build_drfx()
    print(f"built: {path}")
    for name in EFFECTS:
        print(f"  - {name}")

    if args.install:
        import shutil

        dest = os.path.join(templates_dir(), os.path.basename(path))
        shutil.copy2(path, dest)
        print(f"installed: {dest}")
        print("Restart Resolve, then look in Effects Library > Effects "
              f"> Fusion Effects > {PACK_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
