"""Structural unit tests for the drfx effects generator (no Resolve needed)."""

import re
import sys
import os
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drfx"))

import make_effects  # noqa: E402

TOOL_TYPES = (
    r"(?:MacroOperator|Custom|Transform|Merge|LUTBezier|EllipseMask|"
    r"RectangleMask|FastNoise|ChannelBoolean|BrightnessContrast|SoftGlow|Blur|Displace|TimeStretcher)"
)


class TestEffectStructure:
    def test_all_effects_generate(self):
        for name, gen in make_effects.EFFECTS.items():
            assert len(gen()) > 500, name

    def test_braces_balanced(self):
        for name, gen in make_effects.EFFECTS.items():
            content = gen()
            assert content.count("{") == content.count("}"), name

    def test_effect_contract_single_input(self):
        """Effects have MainInput1 + MainOutput1 but NO MainInput2."""
        for name, gen in make_effects.EFFECTS.items():
            content = gen()
            assert "MainInput1 = InstanceInput" in content, name
            assert "MainInput2" not in content, (
                f"{name}: effects are single-input; MainInput2 makes it a transition"
            )
            assert "MainOutput1 = InstanceOutput" in content, name

    def test_root_is_macro_operator(self):
        for name, gen in make_effects.EFFECTS.items():
            assert re.search(r"Tools = ordered\(\) \{\n\t\t\w+ = MacroOperator", gen()), name

    def test_static_effects_have_no_progress_expressions(self):
        """Effects are static — comp.RenderEnd is a transition concept.
        (Per-frame animation via bare `time` is allowed, e.g. Film Grain.)"""
        for name, gen in make_effects.EFFECTS.items():
            assert "comp.RenderEnd" not in gen(), name

    def test_no_version_pinned_ofx(self):
        for name, gen in make_effects.EFFECTS.items():
            assert "ofx.com.blackmagicdesign" not in gen(), name

    def test_no_vestigial_nodes(self):
        for name, gen in make_effects.EFFECTS.items():
            content = gen()
            assert "MediaIn" not in content, name
            assert "AudioDisplay" not in content, name
            assert "CustomData" not in content, name

    def test_sourceop_references_resolve(self):
        for name, gen in make_effects.EFFECTS.items():
            content = gen()
            declared = set(re.findall(rf"(\w+) = {TOOL_TYPES} \{{", content))
            referenced = set(re.findall(r'SourceOp = "(\w+)"', content))
            missing = referenced - declared
            assert not missing, f"{name}: SourceOp references undeclared: {missing}"

    def test_expressions_reference_declared_tools(self):
        for name, gen in make_effects.EFFECTS.items():
            content = gen()
            declared = set(re.findall(rf"(\w+) = {TOOL_TYPES} \{{", content))
            for expr in re.findall(r'Expression = "([^"]+)"', content):
                for tool in re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\.[A-Za-z_]", expr):
                    if tool in ("comp",):
                        continue
                    assert tool in declared, (
                        f"{name}: expression references undeclared {tool!r}: {expr}"
                    )

    def test_masks_connect_via_effect_mask(self):
        """Vignette/Letterbox: mask tools feed an EffectMask input."""
        for name in ("Vignette", "Letterbox 2.39"):
            content = make_effects.EFFECTS[name]()
            assert "EffectMask = Input" in content, name
            assert re.search(r'Source = "Mask"', content), name

    def test_film_grain_animates_per_frame(self):
        """Grain must vary per frame: either FastNoise's built-in SeetheRate
        or an explicit time expression."""
        content = make_effects.EFFECTS["Film Grain"]()
        seethe = re.search(r"SeetheRate = Input \{ Value = [^0]", content)
        time_expr = re.search(r'Expression = "[^"]*\btime\b', content)
        assert seethe or time_expr, (
            "grain must vary per frame (SeetheRate or time expression)"
        )


class TestDrfxPackaging:
    def test_build(self, tmp_path):
        path = make_effects.build_drfx(out_dir=str(tmp_path))
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert all(n.startswith(f"Edit/Effects/{make_effects.PACK_NAME}/")
                       for n in names)
            assert len(names) == len(make_effects.EFFECTS)

    def test_zip_contents_match_generators(self, tmp_path):
        path = make_effects.build_drfx(out_dir=str(tmp_path))
        with zipfile.ZipFile(path) as zf:
            for name, gen in make_effects.EFFECTS.items():
                arc = f"Edit/Effects/{make_effects.PACK_NAME}/{name}.setting"
                assert zf.read(arc).decode() == gen()
