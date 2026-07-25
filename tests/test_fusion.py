"""Unit tests for resolve_kit.fusion against fake tools/comps."""

from resolve_kit.fusion import (
    find_tools_by_id,
    first_tool_by_id,
    get_tool_inputs,
    set_tool_inputs,
)
from tests.conftest import FakeComp, FakeTimelineItem, FakeTool


def _item_with_tools(*tools):
    comp = FakeComp(tools={i + 1: t for i, t in enumerate(tools)})
    return FakeTimelineItem(comps=[comp]), comp


class TestFindTools:
    def test_finds_matching(self):
        t1, t2 = FakeTool(), FakeTool()
        t2.ID = "Background"
        item, comp = _item_with_tools(t1, t2)
        found = list(find_tools_by_id(item, "TextPlus"))
        assert found == [(t1, comp)]

    def test_first_tool(self):
        t1, t2 = FakeTool(), FakeTool()
        item, _ = _item_with_tools(t1, t2)
        tool, comp = first_tool_by_id(item, "TextPlus")
        assert tool is t1 and comp is not None

    def test_first_tool_none_when_missing(self):
        item, _ = _item_with_tools()
        assert first_tool_by_id(item, "TextPlus") == (None, None)

    def test_no_comps(self):
        item = FakeTimelineItem(comps=[])
        assert list(find_tools_by_id(item)) == []


class TestGetSetInputs:
    def test_get_skips_none(self):
        tool = FakeTool(inputs={"Size": 0.5, "Font": None})
        vals = get_tool_inputs(tool, FakeComp(), ["Size", "Font", "Missing"])
        assert vals == {"Size": 0.5}

    def test_set_writes(self):
        tool = FakeTool()
        mismatches = set_tool_inputs(tool, FakeComp(), {"Size": 0.7})
        assert mismatches == {}
        assert tool.GetInput("Size") == 0.7

    def test_set_without_verify_misses_lying_setter(self):
        tool = FakeTool(sticky={"Font"})
        mismatches = set_tool_inputs(tool, FakeComp(), {"Font": "Helvetica"})
        assert mismatches == {}  # silent failure invisible without verify

    def test_set_with_verify_catches_lying_setter(self):
        tool = FakeTool(inputs={"Font": "Arial"}, sticky={"Font"})
        mismatches = set_tool_inputs(tool, FakeComp(), {"Font": "Helvetica"},
                                     verify=True)
        assert mismatches == {"Font": "Arial"}

    def test_set_with_verify_all_ok(self):
        tool = FakeTool()
        mismatches = set_tool_inputs(tool, FakeComp(),
                                     {"Size": 1.0, "Font": "Helvetica"},
                                     verify=True)
        assert mismatches == {}
