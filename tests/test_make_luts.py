"""Unit tests for the .cube LUT generator (no Resolve needed)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drfx"))

import make_luts  # noqa: E402


class TestColorMath:
    def test_clamp(self):
        assert make_luts.clamp(-1) == 0.0
        assert make_luts.clamp(2) == 1.0
        assert make_luts.clamp(0.5) == 0.5

    def test_luma_white_is_one(self):
        assert abs(make_luts.luma(1, 1, 1) - 1.0) < 1e-9

    def test_saturate_identity(self):
        assert make_luts.saturate(0.3, 0.5, 0.7, 1.0) == (0.3, 0.5, 0.7)

    def test_saturate_zero_is_grey(self):
        r, g, b = make_luts.saturate(0.3, 0.5, 0.7, 0.0)
        assert r == g == b

    def test_scurve_identity_at_zero_strength(self):
        for x in (0.0, 0.25, 0.5, 0.75, 1.0):
            assert make_luts.scurve(x, 0.0) == x

    def test_scurve_preserves_endpoints(self):
        for s in (0.3, 0.6, 1.0):
            assert make_luts.scurve(0.0, s) == 0.0
            assert make_luts.scurve(1.0, s) == 1.0


class TestLooks:
    @pytest.mark.parametrize("name", list(make_luts.LOOKS))
    def test_output_in_gamut(self, name):
        look = make_luts.LOOKS[name]
        for r in (0.0, 0.25, 0.5, 0.75, 1.0):
            for g in (0.0, 0.5, 1.0):
                for b in (0.0, 0.5, 1.0):
                    out = look(r, g, b)
                    assert len(out) == 3
                    assert all(0.0 <= v <= 1.0 for v in out), (name, r, g, b, out)

    # Looks that intentionally depart from "white stays bright":
    # Midnight is a day-for-night grade — highlights are crushed by design.
    DARK_LOOKS = {"mvarge Midnight"}

    @pytest.mark.parametrize("name", list(make_luts.LOOKS))
    def test_black_stays_dark_white_stays_bright(self, name):
        """Creative looks may lift/crush but must not invert, and must keep
        a usable tonal range."""
        look = make_luts.LOOKS[name]
        black = make_luts.luma(*look(0, 0, 0))
        white = make_luts.luma(*look(1, 1, 1))
        assert black < 0.12, name
        floor = 0.5 if name in self.DARK_LOOKS else 0.88
        assert white > floor, name
        assert white - black > 0.45, f"{name}: tonal range collapsed"

    def test_mono_crush_is_monochrome(self):
        for rgb in ((0.2, 0.5, 0.8), (0.9, 0.1, 0.4)):
            r, g, b = make_luts.LOOKS["mvarge Mono Crush"](*rgb)
            assert r == g == b


class TestCubeFormat:
    def test_file_structure(self, tmp_path):
        paths = make_luts.build_luts(out_dir=str(tmp_path))
        assert len(paths) == len(make_luts.LOOKS)
        for path in paths:
            lines = open(path).read().splitlines()
            assert lines[0].startswith('TITLE "')
            assert lines[1] == f"LUT_3D_SIZE {make_luts.SIZE}"
            data = [l for l in lines if l and l[0].isdigit() or l.startswith("0")]
            # size^3 data rows, three floats each
            rows = [l for l in lines[4:] if l.strip()]
            assert len(rows) == make_luts.SIZE ** 3
            first = rows[0].split()
            assert len(first) == 3
            float(first[0])  # parseable

    def test_identity_corners(self, tmp_path):
        """First row is black-ish, last row keeps a usable highlight,
        for every look (day-for-night looks crush highlights by design)."""
        paths = make_luts.build_luts(out_dir=str(tmp_path))
        for path in paths:
            rows = [l for l in open(path).read().splitlines()[4:] if l.strip()]
            first = [float(v) for v in rows[0].split()]
            last = [float(v) for v in rows[-1].split()]
            assert make_luts.luma(*first) < 0.12, path
            assert make_luts.luma(*last) > 0.5, path
