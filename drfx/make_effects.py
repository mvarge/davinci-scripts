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


def expr_input(expr: str, value=0) -> str:
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


# Registry: display name -> generator callable
EFFECTS: dict = {
    "Vignette": vignette_setting,
    "Letterbox 2.39": letterbox_setting,
    "Film Grain": film_grain_setting,
    "Chromatic Aberration": chromatic_aberration_setting,
    "Punch Glow": punch_glow_setting,
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
