"""Structural unit tests for the drfx titles generator (no Resolve needed)."""

import re
import sys
import os
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drfx"))

import make_titles  # noqa: E402

TOOL_TYPES = (
    r"(?:MacroOperator|Custom|Transform|Merge|LUTBezier|TextPlus|Background|"
    r"RectangleMask|ChannelBoolean|SoftGlow|Blur)"
)


class TestTitleStructure:
    def test_all_titles_generate(self):
        for name, gen in make_titles.TITLES.items():
            assert len(gen()) > 500, name

    def test_braces_balanced(self):
        for name, gen in make_titles.TITLES.items():
            content = gen()
            assert content.count("{") == content.count("}"), name

    def test_title_contract_generator_no_inputs(self):
        """Titles are generators: MainOutput1 but NO MainInput at all."""
        for name, gen in make_titles.TITLES.items():
            content = gen()
            assert "MainInput1" not in content, (
                f"{name}: titles are generators; a MainInput makes it an effect"
            )
            assert "MainInput2" not in content, name
            assert "MainOutput1 = InstanceOutput" in content, name

    def test_root_is_macro_operator(self):
        for name, gen in make_titles.TITLES.items():
            assert re.search(r"Tools = ordered\(\) \{\n\t\t\w+ = MacroOperator", gen()), name

    def test_every_title_has_a_textplus(self):
        for name, gen in make_titles.TITLES.items():
            assert "TextPlus" in gen(), name

    def test_no_transition_progress_expressions(self):
        """Intros animate over Inspector-set frame counts, not clip length —
        comp.RenderEnd would break when a title is trimmed long."""
        for name, gen in make_titles.TITLES.items():
            assert "comp.RenderEnd" not in gen(), name

    def test_intros_are_bounded(self):
        """Every time-driven intro must saturate via min(1, ...) so the title
        holds a stable end state when trimmed longer than the intro."""
        for name, gen in make_titles.TITLES.items():
            content = gen()
            time_exprs = [e for e in re.findall(r'Expression = "([^"]+)"', content)
                          if "time" in e]
            assert time_exprs, f"{name}: no animation at all?"
            for expr in time_exprs:
                # Bounded either by the saturating progress ramp or by a
                # decaying (1 - P) factor, or by sin() flicker (bounded).
                assert "min(1," in expr or "sin(" in expr, (
                    f"{name}: unbounded time expression: {expr}"
                )

    def test_no_version_pinned_ofx(self):
        for name, gen in make_titles.TITLES.items():
            assert "ofx.com.blackmagicdesign" not in gen(), name

    def test_no_vestigial_nodes(self):
        for name, gen in make_titles.TITLES.items():
            content = gen()
            assert "MediaIn" not in content, name
            assert "AudioDisplay" not in content, name
            assert "CustomData" not in content, name

    def test_no_frame_keyed_splines(self):
        """Frame-keyed BezierSplines don't rescale with trims — the stock
        templates need a KeyframeStretcher to cope; we use expressions."""
        for name, gen in make_titles.TITLES.items():
            assert "BezierSpline" not in gen(), name
            assert "KeyStretcher" not in gen(), name

    def test_sourceop_references_resolve(self):
        for name, gen in make_titles.TITLES.items():
            content = gen()
            declared = set(re.findall(rf"(\w+) = {TOOL_TYPES} \{{", content))
            referenced = set(re.findall(r'SourceOp = "(\w+)"', content))
            missing = referenced - declared
            assert not missing, f"{name}: SourceOp references undeclared: {missing}"

    def test_expressions_reference_declared_tools(self):
        for name, gen in make_titles.TITLES.items():
            content = gen()
            declared = set(re.findall(rf"(\w+) = {TOOL_TYPES} \{{", content))
            for expr in re.findall(r'Expression = "([^"]+)"', content):
                for tool in re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\.[A-Za-z_]", expr):
                    if tool in ("comp",):
                        continue
                    assert tool in declared, (
                        f"{name}: expression references undeclared {tool!r}: {expr}"
                    )

    def test_standard_text_controls_exposed(self):
        """Every title must expose Text, Font/Style, Color clones and Size,
        matching the stock Jitter title's InstanceInput sources."""
        for name, gen in make_titles.TITLES.items():
            content = gen()
            for source in ("StyledText", "Font", "Style", "Red1Clone",
                           "Green1Clone", "Blue1Clone", "Alpha1Clone",
                           '"Size"'):
                assert re.search(rf'Source = "?{source.strip(chr(34))}"?,', content), (
                    f"{name}: missing exposed control {source}"
                )

    def test_fades_carry_alpha(self):
        """Any title that fades in must merge over the transparent Background
        so alpha animates too (a Gain fade would leave alpha solid)."""
        for name in ("Shake Reveal", "Scan Smear", "Tracking Expand",
                     "Blur Punch", "Flicker Neon"):
            content = make_titles.TITLES[name]()
            assert "TopLeftAlpha = Input { Value = 0, }" in content, name

    def test_type_on_uses_end_range(self):
        content = make_titles.TITLES["Type On"]()
        assert re.search(r"End = Input \{ Value = 1, Expression", content)

    def test_glitch_slam_recombines_all_channels(self):
        """RGB split must isolate and recombine all three channels."""
        content = make_titles.TITLES["Glitch Slam"]()
        for iso in ("IsoRed", "IsoGreen", "IsoBlue"):
            assert iso in content
        assert content.count('ApplyMode = Input { Value = FuID { "Screen" }, }') == 2


class TestDrfxPackaging:
    def test_build(self, tmp_path):
        path = make_titles.build_drfx(out_dir=str(tmp_path))
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert all(n.startswith(f"Edit/Titles/{make_titles.PACK_NAME}/")
                       for n in names)
            assert len(names) == len(make_titles.TITLES)

    def test_zip_contents_match_generators(self, tmp_path):
        path = make_titles.build_drfx(out_dir=str(tmp_path))
        with zipfile.ZipFile(path) as zf:
            for name, gen in make_titles.TITLES.items():
                arc = f"Edit/Titles/{make_titles.PACK_NAME}/{name}.setting"
                assert zf.read(arc).decode() == gen()
