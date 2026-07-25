"""Unit tests for resolve_kit.introspect against fake bridge objects."""

from resolve_kit.introspect import ReadbackResult, has_method, verify_by_readback
from tests.conftest import FakeTimeline, FakeTool


class TestHasMethod:
    def test_real_method(self):
        assert has_method(FakeTimeline(), "GetMarkers")

    def test_fabricated_method(self):
        tl = FakeTimeline()
        # the trap: hasattr says yes, has_method says no
        assert hasattr(tl, "TotallyMadeUpMethod")
        assert not has_method(tl, "TotallyMadeUpMethod")

    def test_fabricated_call_returns_none_silently(self):
        # document the bridge behavior the helper defends against
        assert FakeTimeline().TotallyMadeUpMethod() is None

    def test_object_where_dir_raises(self):
        class Hostile:
            def __dir__(self):
                raise RuntimeError("bridge error")

        assert not has_method(Hostile(), "anything")


class TestVerifyByReadback:
    def test_honest_success(self):
        tool = FakeTool()
        r = verify_by_readback(
            mutate=lambda: tool.SetInput("Size", 0.5) or True,
            observe=lambda: tool.GetInput("Size"),
            compare=lambda v: v == 0.5,
        )
        assert r.ok and not r.contradiction
        assert bool(r) is True

    def test_lying_setter_detected(self):
        # sticky input: SetInput silently drops the write
        tool = FakeTool(sticky={"Reel Name"})
        r = verify_by_readback(
            mutate=lambda: tool.SetInput("Reel Name", "A001") or True,  # returns True
            observe=lambda: tool.GetInput("Reel Name"),
            compare=lambda v: v == "A001",
        )
        assert not r.ok
        assert r.contradiction  # raw said True, observation said no
        assert bool(r) is False

    def test_default_compare_is_truthiness(self):
        r = verify_by_readback(mutate=lambda: True, observe=lambda: "something")
        assert r.ok

    def test_false_raw_with_real_effect(self):
        # inverse contradiction: mutate returns falsy but the write landed
        tool = FakeTool()
        r = verify_by_readback(
            mutate=lambda: tool.SetInput("Size", 1.0),  # returns None
            observe=lambda: tool.GetInput("Size"),
            compare=lambda v: v == 1.0,
        )
        assert r.ok and r.contradiction

    def test_result_fields(self):
        r = ReadbackResult(ok=True, raw_success=True, observed=42, contradiction=False)
        assert r.observed == 42 and r.raw_success is True
