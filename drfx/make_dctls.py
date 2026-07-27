#!/usr/bin/env python3
"""Generate .dctl files (DaVinci Color Transform Language) for Resolve Studio.

DCTLs are GPU pixel shaders with Inspector UI controls — parametric looks
that .cube LUTs can't express. Spec source: Resolve's official Developer
README (/Library/Application Support/Blackmagic Design/DaVinci Resolve/
Developer/DaVinciCTL/) — see repo docs. Key rules the emitter follows:

- No `#line` directive — Resolve's preprocessor rejects it (21.0.3).
- DEFINE_UI_PARAMS at the top: bare unquoted labels, no trailing semicolon.
- UI param names are injected as file-scope globals, so no helper function
  parameter or local may reuse one. Violating this yields the misleading
  error "main DCTL function's return value must be float3 to represent RGB".
  All shared-helper params are `h`-prefixed to guarantee no collision.
- Every float literal f-suffixed (unsuffixed doubles break Metal/OpenCL).
- Underscore-prefixed math only (_powf, _mix, _saturatef...); helpers are
  __DEVICE__ and defined before the entry function. Note `_mix` IS generic
  over float/float2/float3/float4 per the official README — the `lerp3`
  helper predates that discovery and is kept only because the emitted files
  are verified working; the inline comment claiming otherwise is stale.
- The entry function's `return` must NOT be a direct function call. Resolve
  infers the return type by textually inspecting the return statement, so
  `return lerp3(a, b, t);` fails with "main DCTL function's return value must
  be float3 to represent RGB" even though the callee is declared float3.
  Assign to a local first, then `return make_float3(v.x, v.y, v.z);` (or
  return a bare float3 variable — both verified OK on 21.0.3).
- Entry signature verbatim: transform(int p_Width, int p_Height, int p_X,
  int p_Y, float p_R, float p_G, float p_B) returning make_float3.
- UI params only appear via the ResolveFX DCTL plugin (Color page > OpenFX >
  ResolveFX Color > DCTL); applied as a plain LUT they freeze at defaults.

Install: /Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/
<pack>/ — new files require a Resolve restart to appear in the DCTL List.

Usage:
    python3 drfx/make_dctls.py                 # write dist/dctl/*.dctl
    python3 drfx/make_dctls.py --install       # also copy into the LUT dir
"""

from __future__ import annotations

import argparse
import os
import sys

PACK_NAME = "mvarge DCTL"
DIST = os.path.join(os.path.dirname(__file__), "..", "dist", "dctl")

# Shared __DEVICE__ helpers prepended to every DCTL that requests them.
#
# CRITICAL: every helper parameter is `h`-prefixed. DEFINE_UI_PARAMS injects
# its names as file-scope globals, so a helper parameter sharing a UI param
# name (e.g. `float amount`) breaks the build. Resolve reports this as the
# thoroughly misleading "main DCTL function's return value must be float3 to
# represent RGB" — it does NOT point at the offending line. Live-verified on
# 21.0.3: a helper taking `float amount` alongside
# DEFINE_UI_PARAMS(amount, ...) fails; renaming the parameter fixes it.
# test_no_ui_param_shadowing() enforces this.
HELPERS = """\
__DEVICE__ float luma709(float3 hRgb)
{
    return 0.2126f * hRgb.x + 0.7152f * hRgb.y + 0.0722f * hRgb.z;
}

__DEVICE__ float3 lerp3(float3 hA, float3 hB, float hT)
{
    // manual vector lerp: _mix() overloads with mixed float3/float args
    // are not portable across CUDA/OpenCL/Metal backends
    return hA + (hB - hA) * _saturatef(hT);
}

__DEVICE__ float3 sat_adjust(float3 hRgb, float hAmt)
{
    // hAmt 1 = unchanged, 0 = grayscale, >1 boosts
    float hY = luma709(hRgb);
    float hK = _clampf(hAmt, 0.0f, 4.0f);
    float3 hGrey = make_float3(hY, hY, hY);
    return hGrey + (hRgb - hGrey) * hK;
}

__DEVICE__ float scurve(float hX, float hStrength)
{
    // smoothstep-based contrast around mid; hStrength 0 = identity
    float hXc = _saturatef(hX);
    float hS = hXc * hXc * (3.0f - 2.0f * hXc);
    return _mix(hXc, hS, _saturatef(hStrength));
}
"""


def dctl_file(ui_params: list[str], body: str, tooltips: list[str] = ()) -> str:
    """Assemble a complete .dctl: UI params, helpers, entry function.

    Note: no #line directive — Resolve's own shipped samples don't use it,
    and its DCTL preprocessor is stricter than clang (a leading #line was
    observed to fail 'Error Processing DaVinci CTL' on 21.0.3 while the
    same file passed a clang syntax check)."""
    parts = []
    parts.extend(ui_params)
    parts.extend(tooltips)
    parts.append("")
    parts.append(HELPERS)
    parts.append(
        "__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, "
        "int p_Y, float p_R, float p_G, float p_B)"
    )
    parts.append("{")
    parts.append(body.rstrip())
    parts.append("}")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# DCTLs
# ---------------------------------------------------------------------------

def punch_dctl() -> str:
    """Parametric version of the mvarge Punch look: contrast + saturation
    with a master amount, all on sliders."""
    ui = [
        "DEFINE_UI_PARAMS(amount, Amount, DCTLUI_SLIDER_FLOAT, 1.0, 0.0, 2.0, 0.05)",
        "DEFINE_UI_PARAMS(contrast, Contrast, DCTLUI_SLIDER_FLOAT, 0.45, 0.0, 1.0, 0.05)",
        "DEFINE_UI_PARAMS(saturation, Saturation, DCTLUI_SLIDER_FLOAT, 1.18, 0.0, 2.0, 0.02)",
    ]
    body = """\
    float3 rgb = make_float3(p_R, p_G, p_B);
    float3 graded;
    graded.x = scurve(rgb.x, contrast);
    graded.y = scurve(rgb.y, contrast);
    graded.z = scurve(rgb.z, contrast);
    graded = sat_adjust(graded, saturation);
    float3 out = lerp3(rgb, graded, amount);
    return make_float3(out.x, out.y, out.z);"""
    return dctl_file(ui, body)


def split_tone_dctl() -> str:
    """Shadows toward one color, highlights toward another, with a luma
    pivot — generalizes the Crimson Dove / Teal Orange family."""
    ui = [
        "DEFINE_UI_PARAMS(shadowColor, Shadow Color, DCTLUI_COLOR_PICKER, 0.1, 0.25, 0.35)",
        "DEFINE_UI_PARAMS(highColor, Highlight Color, DCTLUI_COLOR_PICKER, 1.0, 0.75, 0.45)",
        "DEFINE_UI_PARAMS(amount, Amount, DCTLUI_SLIDER_FLOAT, 0.3, 0.0, 1.0, 0.02)",
        "DEFINE_UI_PARAMS(pivot, Pivot, DCTLUI_SLIDER_FLOAT, 0.5, 0.1, 0.9, 0.02)",
        "DEFINE_UI_PARAMS(preserveLuma, Preserve Luma, DCTLUI_CHECK_BOX, 1)",
    ]
    body = """\
    float3 rgb = make_float3(p_R, p_G, p_B);
    float y = _saturatef(luma709(rgb));
    // weights: shadows below pivot, highlights above, smooth falloff
    float hw = _saturatef((y - pivot) / _fmaxf(1.0f - pivot, 0.001f));
    float sw = _saturatef((pivot - y) / _fmaxf(pivot, 0.001f));
    float3 shadowTint = make_float3(shadowColor.r, shadowColor.g, shadowColor.b);
    float3 highTint = make_float3(highColor.r, highColor.g, highColor.b);
    float3 tinted = rgb;
    tinted = lerp3(tinted, tinted * (2.0f * shadowTint), sw * amount);
    tinted = lerp3(tinted, tinted * (2.0f * highTint), hw * amount);
    if (preserveLuma) {
        float yNew = luma709(tinted);
        float scale = yNew > 0.001f ? y / yNew : 1.0f;
        tinted = tinted * scale;
    }
    tinted.x = _saturatef(tinted.x);
    tinted.y = _saturatef(tinted.y);
    tinted.z = _saturatef(tinted.z);
    return tinted;"""
    return dctl_file(ui, body)


def rgb_crosstalk_dctl() -> str:
    """Film-style channel bleed: each output channel picks up a fraction of
    the other two. Subtle amounts read as 'analog'."""
    ui = [
        "DEFINE_UI_PARAMS(amount, Amount, DCTLUI_SLIDER_FLOAT, 0.15, 0.0, 0.5, 0.01)",
        "DEFINE_UI_PARAMS(warmth, Warmth Bias, DCTLUI_SLIDER_FLOAT, 0.0, -1.0, 1.0, 0.05)",
    ]
    body = """\
    float3 rgb = make_float3(p_R, p_G, p_B);
    float a = _clampf(amount, 0.0f, 0.5f);
    // warmth bias skews the bleed matrix toward red (+) or blue (-)
    float wr = _saturatef(0.5f + 0.5f * warmth);
    float wb = 1.0f - wr;
    float r = (1.0f - a) * rgb.x + a * (wr * rgb.y + (1.0f - wr) * rgb.z);
    float g = (1.0f - a) * rgb.y + a * 0.5f * (rgb.x + rgb.z);
    float b = (1.0f - a) * rgb.z + a * (wb * rgb.y + (1.0f - wb) * rgb.x);
    return make_float3(r, g, b);"""
    return dctl_file(ui, body)


def film_grain_dctl() -> str:
    """Animated exposure-weighted grain using RAND + TIMELINE_FRAME_INDEX.
    NOTE: must be used via the ResolveFX DCTL plugin — applied as a plain
    LUT the frame index freezes at 1 and the grain is static."""
    ui = [
        "DEFINE_UI_PARAMS(amount, Amount, DCTLUI_SLIDER_FLOAT, 0.06, 0.0, 0.3, 0.005)",
        "DEFINE_UI_PARAMS(size, Grain Size, DCTLUI_SLIDER_INT, 1, 1, 4, 1)",
        "DEFINE_UI_PARAMS(shadowWeight, Shadow Weight, DCTLUI_SLIDER_FLOAT, 0.7, 0.0, 1.0, 0.05)",
    ]
    body = """\
    float3 rgb = make_float3(p_R, p_G, p_B);
    // coarser grain: quantize pixel coords by size
    int gx = p_X / max(size, 1);
    int gy = p_Y / max(size, 1);
    uint seed = (uint)(TIMELINE_FRAME_INDEX) * (uint)(p_Width * p_Height)
              + (uint)(gy * p_Width + gx);
    float n = RAND(seed) - 0.5f;
    // film grain lives mostly in mids/shadows; fade out in highlights
    float y = _saturatef(luma709(rgb));
    float weight = _mix(1.0f, 1.0f - y, _saturatef(shadowWeight));
    float g = n * amount * weight;
    return make_float3(rgb.x + g, rgb.y + g, rgb.z + g);"""
    return dctl_file(ui, body)


DCTLS = {
    "mvarge Punch": punch_dctl,
    "mvarge Split Tone": split_tone_dctl,
    "mvarge RGB Crosstalk": rgb_crosstalk_dctl,
    "mvarge Film Grain": film_grain_dctl,
}


def build_dctls(out_dir: str = DIST) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, gen in DCTLS.items():
        path = os.path.join(out_dir, f"{name}.dctl")
        with open(path, "w") as f:
            f.write(gen())
        paths.append(path)
    return paths


def resolve_lut_dir() -> str:
    return f"/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/{PACK_NAME}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true",
                        help="copy .dctl files into Resolve's LUT dir")
    args = parser.parse_args()

    paths = build_dctls()
    print(f"built {len(paths)} DCTLs in {DIST}")
    for p in paths:
        print(f"  - {os.path.basename(p)}")

    if args.install:
        import shutil

        dest = resolve_lut_dir()
        os.makedirs(dest, exist_ok=True)
        for p in paths:
            shutil.copy2(p, dest)
        print(f"installed to: {dest}")
        print("Restart Resolve, then: Color page > OpenFX > ResolveFX Color > "
              "DCTL > pick from the DCTL List (UI sliders only work through "
              "the plugin, not LUT application).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
