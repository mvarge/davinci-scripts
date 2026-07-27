"""Unit tests for the DCTL generator (no Resolve needed).

Structural checks derived from the official DaVinciCTL README rules:
f-suffixed float literals, exact entry signature, underscore math,
define-before-use, UI param syntax.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drfx"))

import make_dctls  # noqa: E402

ENTRY_SIG = (
    "__DEVICE__ float3 transform(int p_Width, int p_Height, int p_X, "
    "int p_Y, float p_R, float p_G, float p_B)"
)


class TestDctlStructure:
    def test_all_generate(self):
        for name, gen in make_dctls.DCTLS.items():
            assert len(gen()) > 300, name

    def test_no_preprocessor_directives(self):
        """Resolve's DCTL preprocessor rejected a leading #line on 21.0.3
        ('Error Processing DaVinci CTL') — official samples ship none.
        First line must be a UI param or code, and no # directives at all."""
        for name, gen in make_dctls.DCTLS.items():
            content = gen()
            for line in content.splitlines():
                assert not line.lstrip().startswith("#"), (
                    f"{name}: preprocessor directive: {line}"
                )
            first = content.splitlines()[0]
            assert first.startswith("DEFINE_UI_PARAMS") or first.startswith("__"), name

    def test_exact_entry_signature(self):
        """The README requires the signature verbatim, parameter names included."""
        for name, gen in make_dctls.DCTLS.items():
            assert ENTRY_SIG in gen(), name

    def test_braces_balanced(self):
        for name, gen in make_dctls.DCTLS.items():
            content = gen()
            assert content.count("{") == content.count("}"), name

    def test_returns_float3(self):
        for name, gen in make_dctls.DCTLS.items():
            assert re.search(r"return (make_float3\(|_mix\(|tinted)", gen()), name

    def test_entry_return_is_not_a_function_call(self):
        """The entry function's return must not be a bare function call.

        Live-verified on 21.0.3 by differential probe: two DCTLs identical
        except for the return statement — `return helper_vec(rgb, amount);`
        FAILED while `float3 out = helper_vec(rgb, amount); return
        make_float3(out.x, out.y, out.z);` PASSED. Resolve infers the entry
        return type by textually inspecting the return expression rather than
        resolving the callee's declared type, and reports any mismatch as
        "main DCTL function's return value must be float3 to represent RGB"
        — an error that names neither the real cause nor a line number.

        Returning a bare float3 variable (`return tinted;`) is also fine.
        Only a direct call expression breaks it.
        """
        call_re = re.compile(r"^\s*return\s+(?!make_float3\b)(\w+)\s*\(")
        for name, gen in make_dctls.DCTLS.items():
            content = gen()
            # isolate the entry function body (last occurrence of the sig)
            body = content.split(ENTRY_SIG, 1)[1]
            for line in body.splitlines():
                m = call_re.match(line)
                assert not m, (
                    f"{name}: entry returns a direct call to "
                    f"'{m.group(1)}()'; assign to a local and return "
                    f"make_float3(...) instead — Resolve will reject this "
                    f"with a misleading float3 return-type error"
                )

    def test_float_literals_are_f_suffixed(self):
        """Unsuffixed double literals are the #1 Metal/OpenCL compile killer.
        Scan for numeric literals with a decimal point not followed by f
        (excluding UI param lines where ints are legitimate)."""
        for name, gen in make_dctls.DCTLS.items():
            for i, line in enumerate(gen().splitlines(), 1):
                if "DEFINE_UI_PARAMS" in line or line.strip().startswith("//"):
                    continue
                bad = re.findall(r"\d+\.\d+(?![0-9]*f)", line)
                assert not bad, f"{name} line {i}: unsuffixed float(s) {bad}: {line.strip()}"

    def test_ui_params_no_trailing_semicolon(self):
        for name, gen in make_dctls.DCTLS.items():
            for line in gen().splitlines():
                if line.startswith("DEFINE_UI_PARAMS"):
                    assert not line.rstrip().endswith(";"), f"{name}: {line}"

    def test_ui_labels_no_commas_inside(self):
        """Combo/labels may not contain commas (README rule). Check label
        field (2nd arg) has no embedded quotes-commas weirdness."""
        for name, gen in make_dctls.DCTLS.items():
            for line in gen().splitlines():
                if line.startswith("DEFINE_UI_PARAMS"):
                    label = line.split(",")[1].strip()
                    assert '"' not in label, f"{name}: quoted label: {line}"

    def test_no_unprefixed_math(self):
        """Generated code must use the documented underscore-prefixed math
        (powf/logf/sqrtf without underscore are not in the DCTL set)."""
        for name, gen in make_dctls.DCTLS.items():
            for line in gen().splitlines():
                if line.strip().startswith("//"):
                    continue
                assert not re.search(r"(?<![\w_])(powf|logf|expf|sqrtf|fminf|fmaxf|clampf|saturatef|mix)\(", line), (
                    f"{name}: unprefixed math call: {line.strip()}"
                )

    def test_helpers_defined_before_entry(self):
        """__DEVICE__ helpers must precede the transform() entry."""
        for name, gen in make_dctls.DCTLS.items():
            content = gen()
            entry_pos = content.index("float3 transform(")
            for helper in ("luma709", "sat_adjust", "scurve"):
                if f"__DEVICE__ float" in content and helper in content:
                    assert content.index(helper) < entry_pos, f"{name}: {helper} after entry"

    def test_grain_uses_frame_index_and_rand(self):
        content = make_dctls.DCTLS["mvarge Film Grain"]()
        assert "TIMELINE_FRAME_INDEX" in content
        assert "RAND(" in content

    def test_mix_arguments_clamped(self):
        """_mix with mix-factor outside [0,1] is undefined per the README;
        every _mix call must clamp/saturate its third argument (or pass a
        UI param already bounded to [0,1])."""
        bounded_vars = set()
        for name, gen in make_dctls.DCTLS.items():
            content = gen()
            code = "\n".join(l for l in content.splitlines()
                             if not l.strip().startswith("//"))
            # UI params with min>=0 and max<=1 are inherently safe
            for m in re.finditer(
                r"DEFINE_UI_PARAMS\((\w+),[^,]+, DCTLUI_SLIDER_FLOAT, [\d.f]+, ([\d.f-]+), ([\d.f]+)", content
            ):
                var, lo, hi = m.group(1), m.group(2), m.group(3)
                if float(lo.rstrip("f")) >= 0 and float(hi.rstrip("f")) <= 1:
                    bounded_vars.add(var)
            for m in re.finditer(r"_mix\([^;]+,\s*([^);]+)\)", code):
                factor = m.group(1).strip()
                ok = (
                    "_saturatef" in factor
                    or "_clampf" in factor
                    or factor in bounded_vars
                )
                assert ok, f"{name}: unclamped _mix factor: {factor}"


class TestBuild:
    def test_build_writes_files(self, tmp_path):
        paths = make_dctls.build_dctls(out_dir=str(tmp_path))
        assert len(paths) == len(make_dctls.DCTLS)
        for p in paths:
            assert p.endswith(".dctl")
            assert os.path.getsize(p) > 300


class TestClangSyntax:
    """Compile-check every generated DCTL against the stub header with clang.
    Catches type errors and bad expressions before Resolve ever sees them.
    Skipped when clang++ is unavailable (e.g. bare CI runners)."""

    @pytest.mark.parametrize("name", list(make_dctls.DCTLS))
    def test_compiles(self, name, tmp_path):
        import shutil
        import subprocess

        clang = shutil.which("clang++") or shutil.which("g++")
        if not clang:
            pytest.skip("no C++ compiler available")
        stub = os.path.join(os.path.dirname(__file__), "..", "drfx", "dctl_stub.h")
        src = tmp_path / "test.cpp"
        src.write_text(make_dctls.DCTLS[name]())
        result = subprocess.run(
            [clang, "-std=c++14", "-fsyntax-only", "-include", stub,
             "-x", "c++", str(src)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{name}:\n{result.stderr[:2000]}"
