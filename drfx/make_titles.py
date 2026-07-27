#!/usr/bin/env python3
"""Generate DaVinci Resolve Edit-page TITLES (.setting) and pack them into an
installable .drfx archive.

Same serialization spec as drfx/make_pack.py (transitions) and
drfx/make_effects.py (effects), with the title-specific contract:

- A title is a MacroOperator with NO MainInput at all (it is a generator —
  nothing is dropped onto it) and a single MainOutput1. It lives under
  Edit/Titles/<Pack>/ inside the zip and appears in Effects Library >
  Titles > <Pack>.
- The image chain is built around a TextPlus tool. Ground truth for the
  TextPlus serialization (Width/Height + UseFrameFormatSettings, StyledText,
  Font/Style, justification, shading-element numbering like Enabled2 /
  Thickness2 / Red2) comes from the stock Templates.drfx titles (Speed,
  Jitter) shipped inside the Resolve app bundle.
- Text controls are exposed with the same InstanceInput sources the stock
  Jitter title uses: StyledText, Font + Style (ControlGroup 2), the
  Red1Clone/Green1Clone/Blue1Clone/Alpha1Clone color aliases (ControlGroup 3)
  and Size.
- Animation timing: intros do NOT use time/comp.RenderEnd. A title clip can
  be trimmed to any length and the intro should stay snappy, so all intros
  animate over a fixed, Inspector-exposed frame count:
      P = min(1, time / max(1, Params.NumberIn1))
  Outros are the one sanctioned comp.RenderEnd use: an outro must anchor to
  the end of the clip whatever its trim, so it counts down frames remaining:
      Pout = min(1, (comp.RenderEnd - time) / max(1, frames))
  Stock titles use frame-keyed BezierSplines + KeyframeStretcher instead;
  expressions are used here because they are the proven pattern in this repo
  and need no keyframe surgery when retimed.
- TextPlus shading elements: ElementShape<N> is the "Appearance" combo,
  serialized 0-based (live probe: {0 Text Fill, 1 Text Outline, 2 Border
  Fill, 3 Border Outline}). Element 1 defaults to Text Fill — do NOT emit
  ElementShape1 = 1 (that turns every title into hollow outlines; the stock
  Jitter title only does it on a hidden displacement-source layer).
  Elements 2-8 carry preset UI roles (2 = red outline, 4 = shadow, ...), so
  stock templates just flip Enabled<N> without setting ElementShape<N>.
- Output alpha: fade-ins go through a Merge over a fully transparent
  Background (all four TopLeft channels 0) so alpha fades with the text.
  A BrightnessContrast Gain fade would dim RGB but leave alpha solid.

Usage:
    python3 drfx/make_titles.py                 # build dist/<pack>.drfx
    python3 drfx/make_titles.py --install       # build + copy into Resolve Templates
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

PACK_NAME = "mvarge Titles"
DIST = os.path.join(os.path.dirname(__file__), "..", "dist")

LUT_COLORS = [(204, 0, 0), (0, 204, 0), (0, 0, 204), (180, 180, 180)]

# ChannelBoolean combo values (0-based, from live probe — see make_effects.py)
CB_RED_BG = 5
CB_GREEN_BG = 6
CB_BLUE_BG = 7
CB_ALPHA_BG = 8
CB_BLACK = 15

# Normalized intro progress: 0..1 over the first NumberIn1 frames, then holds
# at 1 for the rest of the title, however long it is trimmed.
P = "min(1, time / max(1, Params.NumberIn1))"
EASE_OUT = f"(1 - (1 - {P})^3)"                     # fast start, soft landing
# easeOutBack (s = 1.70158): overshoots ~10% past 1 then settles.
BACK_OUT = f"(1 + 2.70158 * ({P} - 1)^3 + 1.70158 * ({P} - 1)^2)"


# ---------------------------------------------------------------------------
# Emission helpers (same dialect as make_pack.py / make_effects.py;
# kept self-contained on purpose)
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
    """A Custom tool named Params exposing tunable numbers (NumberIn1..N)."""
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
                   default=None, max_scale=None, control_group=None) -> str:
    fields = [f'\t\t\t\t\tSourceOp = "{source_op}",', f'\t\t\t\t\tSource = "{source}",']
    if name:
        fields.append(f'\t\t\t\t\tName = "{name}",')
    if control_group is not None:
        fields.append(f'\t\t\t\t\tControlGroup = {control_group},')
    if default is not None:
        fields.append(f'\t\t\t\t\tDefault = {default},')
    if max_scale is not None:
        fields.append(f'\t\t\t\t\tMaxScale = {max_scale},')
    fields.append('\t\t\t\t\tPage = "Controls",')
    body = "\n".join(fields)
    return f"\t\t\t\t{key} = InstanceInput {{\n{body}\n\t\t\t\t}}"


def text_controls(txt: str = "Txt", size: float = 0.12) -> list[dict]:
    """The standard exposed text controls, matching the stock Jitter title's
    InstanceInput sources (Font/Style grouped, RGBA color clones grouped)."""
    return [
        dict(source_op=txt, source="StyledText", name="Text"),
        dict(source_op=txt, source="Font", control_group=2),
        dict(source_op=txt, source="Style", control_group=2),
        dict(source_op=txt, source="Red1Clone", name="Color", control_group=3, default=1),
        dict(source_op=txt, source="Green1Clone", control_group=3, default=1),
        dict(source_op=txt, source="Blue1Clone", control_group=3, default=1),
        dict(source_op=txt, source="Alpha1Clone", control_group=3, default=1),
        dict(source_op=txt, source="Size", name="Size", default=size, max_scale=0.5),
    ]


def macro(name: str, output_op: str, controls: list[dict], tools_lua: str) -> str:
    """Assemble a complete title .setting: MacroOperator with no MainInput."""
    inputs = [
        f'\t\t\t\tComments = Input {{ Value = "{PACK_NAME} — generated by drfx/make_titles.py", }},',
    ]
    for i, ctrl in enumerate(controls, start=1):
        inputs.append(instance_input(f"Input{i}", **ctrl) + ",")
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


def text_tool(name: str = "Txt", extra: dict[str, str] | None = None,
              text: str = "TITLE", font: str = "Open Sans", style: str = "Bold",
              size: float = 0.12, pos: tuple[int, int] = (-330, 33),
              last: bool = False) -> str:
    """A TextPlus with the stock-template baseline serialization.

    NB: no ElementShape1 — element 1 must stay at its default (0, Text Fill).
    """
    inputs: dict[str, str] = {
        "Width": "Input { Value = 1920, }",
        "Height": "Input { Value = 1080, }",
        "UseFrameFormatSettings": "Input { Value = 1, }",
        "StyledText": f'Input {{ Value = "{text}", }}',
        "Font": f'Input {{ Value = "{font}", }}',
        "Style": f'Input {{ Value = "{style}", }}',
        "Size": f"Input {{ Value = {size}, }}",
        "VerticalJustificationNew": "Input { Value = 3, }",
        "HorizontalJustificationNew": "Input { Value = 3, }",
    }
    if extra:
        inputs.update(extra)
    return tool(name, "TextPlus", inputs, pos, last)


def transparent_bg(name: str = "Bg", pos: tuple[int, int] = (-110, 99)) -> str:
    """Fully transparent Background — Merge base so fades carry alpha."""
    return tool(name, "Background", {
        "UseFrameFormatSettings": "Input { Value = 1, }",
        "TopLeftRed": "Input { Value = 0, }",
        "TopLeftGreen": "Input { Value = 0, }",
        "TopLeftBlue": "Input { Value = 0, }",
        "TopLeftAlpha": "Input { Value = 0, }",
    }, pos)


def fade_merge(name: str, bg: str, fg: str, blend_expr: str,
               pos: tuple[int, int] = (0, 99), effect_mask: str | None = None,
               last: bool = True) -> str:
    inputs: dict[str, str] = {
        "Blend": expr_input(blend_expr, 1),
        "PerformDepthMerge": "Input { Value = 0, }",
        "Background": src_input(bg),
        "Foreground": src_input(fg),
    }
    if effect_mask:
        inputs = {"EffectMask": src_input(effect_mask, "Mask"), **inputs}
    return tool(name, "Merge", inputs, pos, last)


# ---------------------------------------------------------------------------
# Title generators
# ---------------------------------------------------------------------------

def glitch_slam_setting() -> str:
    """Text slams in oversized with decaying RGB channel split + positional
    shake, lands clean. RGB split = proven ChannelBoolean isolate + Screen
    recombine pattern from make_effects.py chromatic aberration."""
    shift = f"Params.NumberIn2 * (1 - {EASE_OUT})"

    def channel_iso(name: str, to_red: int, to_green: int, to_blue: int,
                    pos: tuple[int, int]) -> str:
        return tool(name, "ChannelBoolean", {
            "ToRed": f"Input {{ Value = {to_red}, }}",
            "ToGreen": f"Input {{ Value = {to_green}, }}",
            "ToBlue": f"Input {{ Value = {to_blue}, }}",
            "ToAlpha": f"Input {{ Value = {CB_ALPHA_BG}, }}",
            "Background": src_input("Txt"),
            "Foreground": src_input("Txt"),
        }, pos)

    tools = "\n".join([
        params_tool([("Intro Frames", 18), ("Split Amount", 0.006),
                     ("Shake Amount", 0.004)]),
        text_tool(size=0.16),
        channel_iso("IsoRed", CB_RED_BG, CB_BLACK, CB_BLACK, (-220, 0)),
        channel_iso("IsoGreen", CB_BLACK, CB_GREEN_BG, CB_BLACK, (-220, 33)),
        channel_iso("IsoBlue", CB_BLACK, CB_BLACK, CB_BLUE_BG, (-220, 66)),
        tool("ShiftRed", "Transform", {
            "Center": expr_input(f"Point(0.5 + {shift}, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("IsoRed"),
        }, (-110, 0)),
        tool("ShiftBlue", "Transform", {
            "Center": expr_input(f"Point(0.5 - {shift}, 0.5)", "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("IsoBlue"),
        }, (-110, 66)),
        tool("MergeRG", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("IsoGreen"),
            "Foreground": src_input("ShiftRed"),
        }, (0, 33)),
        tool("MergeRGB", "Merge", {
            "ApplyMode": 'Input { Value = FuID { "Screen" }, }',
            "PerformDepthMerge": "Input { Value = 0, }",
            "Background": src_input("MergeRG"),
            "Foreground": src_input("ShiftBlue"),
        }, (110, 33)),
        tool("Slam", "Transform", {
            "Size": expr_input(f"1 + 1.4 * (1 - {EASE_OUT})", 1),
            "Center": expr_input(
                f"Point(0.5 + Params.NumberIn3 * (1 - {P}) * sin(time * 37.7), "
                f"0.5 + Params.NumberIn3 * (1 - {P}) * sin(time * 29.3))",
                "{ 0.5, 0.5 }"),
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
            "Input": src_input("MergeRGB"),
        }, (220, 33), last=True),
    ])
    return macro("GlitchSlam", "Slam",
                 text_controls(size=0.16) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=18, max_scale=60),
                     dict(source_op="Params", source="NumberIn2",
                          name="Split Amount", default=0.006, max_scale=0.02),
                     dict(source_op="Params", source="NumberIn3",
                          name="Shake Amount", default=0.004, max_scale=0.02),
                 ], tools)


def shake_reveal_setting() -> str:
    """Text pops in with a scale hit and decaying two-axis shake (incommensurate
    sine frequencies read as noise), faded up over transparent alpha."""
    tools = "\n".join([
        params_tool([("Intro Frames", 12), ("Shake Amount", 0.012)]),
        text_tool(size=0.16),
        tool("Shake", "Transform", {
            "Center": expr_input(
                f"Point(0.5 + Params.NumberIn2 * (1 - {P}) * sin(time * 41.3), "
                f"0.5 + Params.NumberIn2 * (1 - {P}) * sin(time * 33.7))",
                "{ 0.5, 0.5 }"),
            "Size": expr_input(f"1 + 0.12 * (1 - {EASE_OUT})", 1),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
            "Input": src_input("Txt"),
        }, (-110, 33)),
        transparent_bg(),
        fade_merge("FadeIn", "Bg", "Shake", EASE_OUT),
    ])
    return macro("ShakeReveal", "FadeIn",
                 text_controls(size=0.16) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=12, max_scale=60),
                     dict(source_op="Params", source="NumberIn2",
                          name="Shake Amount", default=0.012, max_scale=0.05),
                 ], tools)


def scan_smear_setting() -> str:
    """Text whips in horizontally from off-left under heavy directional blur,
    both decaying to a clean landing — whip-pan energy as a title."""
    tools = "\n".join([
        params_tool([("Intro Frames", 16), ("Slide Distance", 0.35)]),
        text_tool(size=0.14),
        tool("Slide", "Transform", {
            "Center": expr_input(
                f"Point(0.5 - Params.NumberIn2 * (1 - {EASE_OUT}), 0.5)",
                "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
            "Input": src_input("Txt"),
        }, (-220, 33)),
        tool("Smear", "Blur", {
            "XBlurSize": expr_input(f"(1 - {EASE_OUT}) * 120 * Params.NumberIn2"),
            "YBlurSize": "Input { Value = 0, }",
            "Input": src_input("Slide"),
        }, (-110, 33)),
        transparent_bg(),
        fade_merge("FadeIn", "Bg", "Smear", f"min(1, 3 * {P})"),
    ])
    return macro("ScanSmear", "FadeIn",
                 text_controls(size=0.14) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=16, max_scale=60),
                     dict(source_op="Params", source="NumberIn2",
                          name="Slide Distance", default=0.35, max_scale=1),
                 ], tools)


def flicker_neon_setting() -> str:
    """Outlined text with a soft glow buzzing on like a faulty neon sign at
    BOTH ends: flickers up over the intro, burns steady through the middle,
    then flickers back out anchored to the end of the clip (comp.RenderEnd
    countdown), whatever its trimmed length. Outline color exposed
    separately from the fill."""
    # Q mirrors P from the tail: 1 through the middle, ramps to 0 at the end.
    q = "min(1, (comp.RenderEnd - time) / max(1, Params.NumberIn1))"
    # steady = the dimmer envelope; activity = 1 near either end, 0 mid-clip
    steady = f"min(1, 0.25 + 0.75 * min({P}, {q}))"
    activity = f"min(1, (1 - {P}) + (1 - {q}))"
    flicker = (f"{steady} * (1 - Params.NumberIn2 * {activity} * "
               f"(0.5 + 0.5 * sin(time * 9.4) * sin(time * 23.1)))")
    tools = "\n".join([
        params_tool([("Intro Frames", 20), ("Flicker Amount", 0.8)]),
        text_tool(size=0.14, extra={
            "Enabled2": "Input { Value = 1, }",
            "Thickness2": "Input { Value = 0.012, }",
            "Softness2": "Input { Value = 1, }",
            "Red2": "Input { Value = 0, }",
            "Green2": "Input { Value = 1, }",
            "Blue2": "Input { Value = 0.8, }",
        }),
        tool("Glow", "SoftGlow", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "Gain": "Input { Value = 4, }",
            "Threshold": "Input { Value = 0.3, }",
            "Input": src_input("Txt"),
        }, (-110, 33)),
        transparent_bg(),
        fade_merge("Flick", "Bg", "Glow", flicker),
    ])
    return macro("FlickerNeon", "Flick",
                 text_controls(size=0.14) + [
                     dict(source_op="Txt", source="Red2", name="Neon Color",
                          control_group=4, default=0),
                     dict(source_op="Txt", source="Green2",
                          control_group=4, default=1),
                     dict(source_op="Txt", source="Blue2",
                          control_group=4, default=0.8),
                     dict(source_op="Glow", source="Gain", name="Glow Amount",
                          default=4, max_scale=10),
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=20, max_scale=90),
                     dict(source_op="Params", source="NumberIn2",
                          name="Flicker Amount", default=0.8, max_scale=1),
                 ], tools)


def type_on_setting() -> str:
    """Per-character write-on using TextPlus's native End range input —
    the reliable stand-in for per-word cascade (Follower modifiers do not
    serialize robustly in hand-built templates)."""
    tools = "\n".join([
        params_tool([("Type Frames", 30)]),
        text_tool(size=0.12, extra={
            "End": expr_input(P, 1),
        }, last=True),
    ])
    return macro("TypeOn", "Txt",
                 text_controls(size=0.12) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Type Frames", default=30, max_scale=120),
                 ], tools)


def tracking_expand_setting() -> str:
    """Classic cinematic: letters start collapsed tight and expand out to
    normal tracking while fading up. Spread = extra starting tracking."""
    tools = "\n".join([
        params_tool([("Intro Frames", 24), ("Spread", 1.5)]),
        text_tool(size=0.1, style="Regular", extra={
            "CharacterSpacingClone": expr_input(
                f"1 + Params.NumberIn2 * (1 - {EASE_OUT})", 1),
        }),
        transparent_bg(),
        fade_merge("FadeIn", "Bg", "Txt", EASE_OUT, pos=(0, 66)),
    ])
    return macro("TrackingExpand", "FadeIn",
                 text_controls(size=0.1) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=24, max_scale=90),
                     dict(source_op="Params", source="NumberIn2",
                          name="Spread", default=1.5, max_scale=4),
                 ], tools)


def line_wipe_lower_third_setting() -> str:
    """Lower third: a colored bar draws on from the center outward, then the
    text rises in above it slightly delayed. Bar color exposed separately."""
    # delayed progress for the text: starts at 60% of the bar's intro
    pd = "min(1, max(0, time - 0.6 * Params.NumberIn1) / max(1, Params.NumberIn1))"
    eod = f"(1 - (1 - {pd})^3)"
    tools = "\n".join([
        params_tool([("Intro Frames", 20), ("Bar Width", 0.42)]),
        tool("BarMask", "RectangleMask", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "SoftEdge": "Input { Value = 0, }",
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "ClippingMode": 'Input { Value = FuID { "None" }, }',
            "Center": "Input { Value = { 0.5, 0.24 }, }",
            "Width": expr_input(f"Params.NumberIn2 * {EASE_OUT}", 0.42),
            "Height": "Input { Value = 0.014, }",
        }, (-330, 99)),
        tool("BarFill", "Background", {
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "TopLeftRed": "Input { Value = 1, }",
            "TopLeftGreen": "Input { Value = 1, }",
            "TopLeftBlue": "Input { Value = 1, }",
            "TopLeftAlpha": "Input { Value = 1, }",
            "EffectMask": src_input("BarMask", "Mask"),
        }, (-220, 99)),
        text_tool(size=0.07, extra={
            "Center": "Input { Value = { 0.5, 0.3 }, }",
        }),
        tool("TxtRise", "Transform", {
            "Center": expr_input(f"Point(0.5, 0.5 - 0.04 * (1 - {eod}))",
                                 "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("Txt"),
        }, (-110, 33)),
        fade_merge("Assemble", "BarFill", "TxtRise", eod),
    ])
    return macro("LineWipeLowerThird", "Assemble",
                 text_controls(size=0.07) + [
                     dict(source_op="BarFill", source="TopLeftRed",
                          name="Bar Color", control_group=4, default=1),
                     dict(source_op="BarFill", source="TopLeftGreen",
                          control_group=4, default=1),
                     dict(source_op="BarFill", source="TopLeftBlue",
                          control_group=4, default=1),
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=20, max_scale=90),
                     dict(source_op="Params", source="NumberIn2",
                          name="Bar Width", default=0.42, max_scale=1),
                 ], tools)


def blur_punch_setting() -> str:
    """Text snaps from heavy defocus to sharp with a slight scale settle and
    a fast alpha ramp — a clean, punchy standard."""
    tools = "\n".join([
        params_tool([("Intro Frames", 14), ("Blur Amount", 1)]),
        text_tool(size=0.15),
        tool("Punch", "Transform", {
            "Size": expr_input(f"1 + 0.08 * (1 - {EASE_OUT})", 1),
            "Edges": "Input { Value = 3, }",
            "Input": src_input("Txt"),
        }, (-220, 33)),
        tool("Soften", "Blur", {
            "XBlurSize": expr_input(f"(1 - {EASE_OUT}) * 40 * Params.NumberIn2"),
            "YBlurSize": expr_input(f"(1 - {EASE_OUT}) * 40 * Params.NumberIn2"),
            "Input": src_input("Punch"),
        }, (-110, 33)),
        transparent_bg(),
        fade_merge("FadeIn", "Bg", "Soften", f"min(1, 2.5 * {P})"),
    ])
    return macro("BlurPunch", "FadeIn",
                 text_controls(size=0.15) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=14, max_scale=60),
                     dict(source_op="Params", source="NumberIn2",
                          name="Blur Amount", default=1, max_scale=3),
                 ], tools)


def rise_reveal_setting() -> str:
    """Editorial mask reveal: text rises from below an invisible horizontal
    window with an easeOutBack overshoot, cropped by a static RectangleMask
    on the final Merge so it emerges from nothing."""
    tools = "\n".join([
        params_tool([("Intro Frames", 22), ("Window Height", 0.32)]),
        text_tool(size=0.14),
        tool("Rise", "Transform", {
            "Center": expr_input(f"Point(0.5, 0.5 - 0.3 * (1 - {BACK_OUT}))",
                                 "{ 0.5, 0.5 }"),
            "Edges": "Input { Value = 3, }",
            "MotionBlur": "Input { Value = 1, }",
            "Quality": "Input { Value = 5, }",
            "ShutterAngle": "Input { Value = 270, }",
            "Input": src_input("Txt"),
        }, (-220, 33)),
        tool("Window", "RectangleMask", {
            "Filter": 'Input { Value = FuID { "Fast Gaussian" }, }',
            "SoftEdge": "Input { Value = 0, }",
            "UseFrameFormatSettings": "Input { Value = 1, }",
            "ClippingMode": 'Input { Value = FuID { "None" }, }',
            "Width": "Input { Value = 1, }",
            "Height": expr_input("Params.NumberIn2", 0.32),
        }, (-330, 99)),
        transparent_bg(),
        fade_merge("Reveal", "Bg", "Rise", "1", effect_mask="Window"),
    ])
    return macro("RiseReveal", "Reveal",
                 text_controls(size=0.14) + [
                     dict(source_op="Params", source="NumberIn1",
                          name="Intro Frames", default=22, max_scale=90),
                     dict(source_op="Params", source="NumberIn2",
                          name="Window Height", default=0.32, max_scale=1),
                 ], tools)


# Registry: display name -> generator callable
TITLES: dict = {
    "Glitch Slam": glitch_slam_setting,
    "Shake Reveal": shake_reveal_setting,
    "Scan Smear": scan_smear_setting,
    "Flicker Neon": flicker_neon_setting,
    "Type On": type_on_setting,
    "Tracking Expand": tracking_expand_setting,
    "Line Wipe Lower Third": line_wipe_lower_third_setting,
    "Blur Punch": blur_punch_setting,
    "Rise Reveal": rise_reveal_setting,
}


def build_drfx(out_dir: str = DIST) -> str:
    os.makedirs(out_dir, exist_ok=True)
    drfx_path = os.path.join(out_dir, f"{PACK_NAME}.drfx")
    with zipfile.ZipFile(drfx_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, generate in TITLES.items():
            arcname = f"Edit/Titles/{PACK_NAME}/{name}.setting"
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
    for name in TITLES:
        print(f"  - {name}")

    if args.install:
        import shutil

        dest = os.path.join(templates_dir(), os.path.basename(path))
        shutil.copy2(path, dest)
        print(f"installed: {dest}")
        print("Restart Resolve, then look in Effects Library > Titles "
              f"> {PACK_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
