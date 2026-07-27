"""Structural unit tests for the drfx transition generator (no Resolve needed)."""

import re
import sys
import os
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "drfx"))

import make_pack  # noqa: E402


class TestSettingStructure:
    def _content(self, name="Zoom Punch"):
        return make_pack.TRANSITIONS[name]()

    def test_all_transitions_generate(self):
        for name, gen in make_pack.TRANSITIONS.items():
            content = gen()
            assert len(content) > 500, name

    def test_braces_balanced(self):
        for name, gen in make_pack.TRANSITIONS.items():
            content = gen()
            assert content.count("{") == content.count("}"), name

    def test_transition_contract(self):
        """MainInput1 + MainInput2 + MainOutput1 = what makes it a transition."""
        content = self._content()
        assert "MainInput1 = InstanceInput" in content
        assert "MainInput2 = InstanceInput" in content
        assert "MainOutput1 = InstanceOutput" in content

    def test_root_is_macro_operator(self):
        content = self._content()
        assert re.search(r"Tools = ordered\(\) \{\n\t\t\w+ = MacroOperator", content)

    def test_animation_is_duration_independent(self):
        """All animation must use time/comp.RenderEnd. Frame-keyed
        BezierSplines don't rescale; TimeStretcher driven by a normalized
        expression is the sanctioned way to retime embedded footage."""
        for name, gen in make_pack.TRANSITIONS.items():
            content = gen()
            assert "comp.RenderEnd" in content, name
            assert "BezierSpline" not in content, (
                f"{name}: frame-keyed BezierSpline does not scale with duration"
            )

    def test_film_burns_reference_existing_sequences(self):
        """Film Burn loaders point at real JPEG sequence files.

        Local-only: the sequences live in Marcelo's media library, which
        doesn't exist on CI runners — skip there, verify here.
        """
        import os

        import pytest

        if not os.path.isdir(make_pack.BURN_SEQ_DIR):
            pytest.skip("burn sequences not present on this machine (CI)")
        for name, gen in make_pack.TRANSITIONS.items():
            if not name.startswith("Film Burn"):
                continue
            content = gen()
            for path in re.findall(r'Filename = "([^"]+)"', content):
                assert os.path.exists(path), f"{name}: missing sequence {path}"

    def test_film_burn_screen_blend(self):
        for name, gen in make_pack.TRANSITIONS.items():
            if not name.startswith("Film Burn"):
                continue
            content = gen()
            assert 'ApplyMode = Input { Value = FuID { "Screen" }' in content, name
            assert "TimeStretcher" in content, name

    def test_no_version_pinned_ofx(self):
        """ResolveFX OFX nodes are version-pinned; stock tools only."""
        for name, gen in make_pack.TRANSITIONS.items():
            assert "ofx.com.blackmagicdesign" not in gen(), name

    def test_no_vestigial_nodes(self):
        for name, gen in make_pack.TRANSITIONS.items():
            content = gen()
            assert "MediaIn" not in content, name
            assert "AudioDisplay" not in content, name
            assert "CustomData" not in content, name

    TOOL_TYPES = r"(?:MacroOperator|Custom|Transform|Dissolve|Blur|LUTBezier|Loader|TimeStretcher|Merge|Background|ChannelBoolean|BrightnessContrast)"

    def test_sourceop_references_resolve(self):
        """Every SourceOp must reference a declared tool name (all transitions)."""
        for name, gen in make_pack.TRANSITIONS.items():
            content = gen()
            declared = set(re.findall(rf"(\w+) = {self.TOOL_TYPES} \{{", content))
            referenced = set(re.findall(r'SourceOp = "(\w+)"', content))
            missing = referenced - declared
            assert not missing, f"{name}: SourceOp references undeclared tools: {missing}"

    def test_expressions_reference_declared_tools(self):
        for name, gen in make_pack.TRANSITIONS.items():
            content = gen()
            declared = set(re.findall(rf"(\w+) = {self.TOOL_TYPES} \{{", content))
            for expr in re.findall(r'Expression = "([^"]+)"', content):
                for tool in re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\.[A-Za-z_]", expr):
                    if tool in ("comp",):  # comp.RenderEnd is a builtin
                        continue
                    assert tool in declared, (
                        f"{name}: expression references undeclared {tool!r}: {expr}"
                    )

    def test_custom_tool_has_lut_boilerplate(self):
        """Custom tools must ship their 4 LUTBezier default splines."""
        content = self._content()
        if " = Custom {" in content:
            for i in range(1, 5):
                assert f"LUTIn{i} = Input {{ SourceOp = " in content, f"LUTIn{i} missing"
                assert f"ParamsLUTIn{i} = LUTBezier" in content, f"ParamsLUTIn{i} missing"


class TestDrfxPackaging:
    def test_build(self, tmp_path):
        path = make_pack.build_drfx(out_dir=str(tmp_path))
        assert path.endswith(".drfx")
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            assert all(n.startswith(f"Edit/Transitions/{make_pack.PACK_NAME}/")
                       for n in names)
            assert all(n.endswith(".setting") for n in names)
            assert len(names) == len(make_pack.TRANSITIONS)

    def test_zip_contents_match_generators(self, tmp_path):
        path = make_pack.build_drfx(out_dir=str(tmp_path))
        with zipfile.ZipFile(path) as zf:
            for name, gen in make_pack.TRANSITIONS.items():
                arc = f"Edit/Transitions/{make_pack.PACK_NAME}/{name}.setting"
                assert zf.read(arc).decode() == gen()
