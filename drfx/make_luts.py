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


LOOKS = {
    "mvarge Punch": look_punch,
    "mvarge Film Fade": look_film_fade,
    "mvarge Teal Orange": look_teal_orange,
    "mvarge Mono Crush": look_mono_crush,
    "mvarge Cold Steel": look_cold_steel,
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
    return os.path.expanduser(
        f"~/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT/{PACK_NAME}"
    )


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
