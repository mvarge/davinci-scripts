#!/usr/bin/env python3
"""Generate .cube LUTs for DaVinci Resolve (or any NLE).

The .cube format is plain text: a header (LUT_3D_SIZE N) followed by N^3
lines of "r g b" floats, blue-major order (b outer, g middle, r inner),
input domain 0..1. Resolve picks LUTs up from its LUT folder; use
"Refresh LUT List" in Project Settings > Color Management, no restart needed.

These are creative Rec.709-in / Rec.709-out looks meant to be applied on
top of normalized footage (e.g. after RCM's HLG->709 conversion).

Usage:
    python3 drfx/make_luts.py                 # write dist/luts/*.cube
    python3 drfx/make_luts.py --install       # also copy into Resolve's LUT dir
"""

from __future__ import annotations

import argparse
import os
import sys

PACK_NAME = "mvarge Looks"
SIZE = 33  # standard cube size; plenty for smooth creative looks
DIST = os.path.join(os.path.dirname(__file__), "..", "dist", "luts")


# ---------------------------------------------------------------------------
# color math helpers (all operate on 0..1 floats)
# ---------------------------------------------------------------------------

def clamp(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def luma(r: float, g: float, b: float) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def saturate(r: float, g: float, b: float, amount: float) -> tuple:
    """amount 1 = unchanged, >1 boosts, <1 desaturates."""
    y = luma(r, g, b)
    return (
        clamp(lerp(y, r, amount)),
        clamp(lerp(y, g, amount)),
        clamp(lerp(y, b, amount)),
    )


def scurve(x: float, strength: float) -> float:
    """Smooth contrast S-curve around 0.5; strength 0 = identity."""
    # smoothstep-based: blend x with 3x^2-2x^3 remap
    s = x * x * (3 - 2 * x)
    return clamp(lerp(x, s, strength))


def lift_gamma_gain(x: float, lift: float, gamma: float, gain: float) -> float:
    """Classic grading primitive on a single channel."""
    v = x * gain + lift * (1 - x)
    v = clamp(v)
    return clamp(v ** (1.0 / gamma)) if gamma > 0 else v


# ---------------------------------------------------------------------------
# looks — each maps (r,g,b) -> (r,g,b)
# ---------------------------------------------------------------------------

def look_punch(r, g, b):
    """Contrast + saturation pop for social delivery."""
    r, g, b = (scurve(v, 0.45) for v in (r, g, b))
    return saturate(r, g, b, 1.18)


def look_film_fade(r, g, b):
    """Faded film: lifted blacks, soft highlights, gentle warmth."""
    r = lift_gamma_gain(r, 0.045, 1.03, 0.97)
    g = lift_gamma_gain(g, 0.04, 1.0, 0.96)
    b = lift_gamma_gain(b, 0.05, 0.97, 0.94)
    return saturate(r, g, b, 0.92)


def look_teal_orange(r, g, b):
    """Shadows toward teal, highlights toward orange, midtone contrast."""
    y = luma(r, g, b)
    # push shadows to teal (subtract red, add blue/green), highlights to orange
    shadow = (1 - y) ** 2
    highlight = y ** 2
    r = clamp(r - 0.06 * shadow + 0.05 * highlight)
    g = clamp(g + 0.02 * shadow + 0.015 * highlight)
    b = clamp(b + 0.07 * shadow - 0.05 * highlight)
    r, g, b = (scurve(v, 0.3) for v in (r, g, b))
    return saturate(r, g, b, 1.08)


def look_mono_crush(r, g, b):
    """High-contrast black & white with crushed shadows — very metal."""
    y = luma(r, g, b)
    y = scurve(y, 0.6)
    y = lift_gamma_gain(y, -0.02, 0.95, 1.05)
    return (y, y, y)


def look_cold_steel(r, g, b):
    """Desaturated blue-steel look for moody sections."""
    r = lift_gamma_gain(r, 0.0, 0.98, 0.94)
    g = lift_gamma_gain(g, 0.005, 1.0, 0.98)
    b = lift_gamma_gain(b, 0.015, 1.04, 1.02)
    r, g, b = (scurve(v, 0.35) for v in (r, g, b))
    return saturate(r, g, b, 0.78)


# --- aggressive tier ---------------------------------------------------------

def look_bleach_bypass(r, g, b):
    """Skip-bleach: harsh contrast, heavy desaturation, hot highlights.
    The war-movie / industrial look."""
    y = luma(r, g, b)
    r, g, b = saturate(r, g, b, 0.35)
    # overlay-blend the luma onto itself for brutal contrast
    def overlay(v):
        return clamp(2 * v * y if y < 0.5 else 1 - 2 * (1 - v) * (1 - y))
    r, g, b = overlay(r), overlay(g), overlay(b)
    return (lift_gamma_gain(r, -0.03, 0.96, 1.08),
            lift_gamma_gain(g, -0.03, 0.96, 1.08),
            lift_gamma_gain(b, -0.03, 0.96, 1.06))


def look_crimson_dove(r, g, b):
    """Crushed blacks, blood-red mids, bone-white highlights. Duotone-ish
    horror grade."""
    y = luma(r, g, b)
    y = scurve(y, 0.7)
    y = lift_gamma_gain(y, -0.04, 0.9, 1.1)
    # map luma through a black -> deep red -> white ramp
    if y < 0.55:
        t = y / 0.55
        return (clamp(t * 0.75), clamp(t * 0.06), clamp(t * 0.08))
    t = (y - 0.55) / 0.45
    return (clamp(0.75 + t * 0.25), clamp(0.06 + t * 0.9), clamp(0.08 + t * 0.88))


def look_toxic(r, g, b):
    """Sickly green-yellow cross-process with crushed teal shadows."""
    y = luma(r, g, b)
    shadow = (1 - y) ** 2
    r = clamp(lift_gamma_gain(r, -0.02, 1.08, 0.95) - 0.05 * shadow)
    g = clamp(lift_gamma_gain(g, 0.01, 0.92, 1.06))
    b = clamp(lift_gamma_gain(b, 0.0, 1.1, 0.8) + 0.04 * shadow)
    r, g, b = (scurve(v, 0.5) for v in (r, g, b))
    return saturate(r, g, b, 1.12)


def look_midnight(r, g, b):
    """Day-for-night: everything plunged toward blue-black, highlights
    barely surviving. For doom sections."""
    r = lift_gamma_gain(r, 0.0, 1.25, 0.55)
    g = lift_gamma_gain(g, 0.0, 1.15, 0.62)
    b = lift_gamma_gain(b, 0.02, 1.0, 0.78)
    r, g, b = (scurve(v, 0.4) for v in (r, g, b))
    return saturate(r, g, b, 0.65)


def look_burnout(r, g, b):
    """Blown warm highlights, chocolate shadows, heavy orange cast —
    overexposed-film-in-the-sun energy."""
    y = luma(r, g, b)
    highlight = y ** 1.5
    r = clamp(lift_gamma_gain(r, 0.03, 0.85, 1.15) + 0.08 * highlight)
    g = clamp(lift_gamma_gain(g, 0.02, 0.95, 1.0) + 0.03 * highlight)
    b = clamp(lift_gamma_gain(b, 0.0, 1.15, 0.72))
    r, g, b = (scurve(v, 0.45) for v in (r, g, b))
    return saturate(r, g, b, 1.05)


LOOKS = {
    "mvarge Punch": look_punch,
    "mvarge Film Fade": look_film_fade,
    "mvarge Teal Orange": look_teal_orange,
    "mvarge Mono Crush": look_mono_crush,
    "mvarge Cold Steel": look_cold_steel,
    "mvarge Bleach Bypass": look_bleach_bypass,
    "mvarge Crimson Dove": look_crimson_dove,
    "mvarge Toxic": look_toxic,
    "mvarge Midnight": look_midnight,
    "mvarge Burnout": look_burnout,
}


# ---------------------------------------------------------------------------
# .cube emission
# ---------------------------------------------------------------------------

def write_cube(path: str, look, size: int = SIZE) -> None:
    n = size - 1
    with open(path, "w") as f:
        f.write(f'TITLE "{os.path.splitext(os.path.basename(path))[0]}"\n')
        f.write(f"LUT_3D_SIZE {size}\n")
        f.write("DOMAIN_MIN 0.0 0.0 0.0\n")
        f.write("DOMAIN_MAX 1.0 1.0 1.0\n")
        for bi in range(size):
            for gi in range(size):
                for ri in range(size):
                    r, g, b = look(ri / n, gi / n, bi / n)
                    f.write(f"{r:.6f} {g:.6f} {b:.6f}\n")


def build_luts(out_dir: str = DIST) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, look in LOOKS.items():
        path = os.path.join(out_dir, f"{name}.cube")
        write_cube(path, look)
        paths.append(path)
    return paths


def resolve_lut_dir() -> str:
    """Resolve's LUT browser scans the SYSTEM LUT folder on macOS
    (/Library/..., world-writable by default), not the user-home one."""
    return f"/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/{PACK_NAME}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true",
                        help="copy .cube files into Resolve's user LUT dir")
    args = parser.parse_args()

    paths = build_luts()
    print(f"built {len(paths)} LUTs in {DIST}")
    for p in paths:
        print(f"  - {os.path.basename(p)}")

    if args.install:
        import shutil

        dest_dir = resolve_lut_dir()
        os.makedirs(dest_dir, exist_ok=True)
        for p in paths:
            shutil.copy2(p, dest_dir)
        print(f"installed to: {dest_dir}")
        print("In Resolve: Project Settings > Color Management > Open LUT Folder /"
              " Refresh — then find them under the LUT browser as "
              f"'{PACK_NAME}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
