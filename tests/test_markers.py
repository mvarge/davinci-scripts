"""Unit tests for resolve_kit.markers against fake Resolve objects."""

import pytest

from resolve_kit.markers import (
    MARKER_COLORS,
    add_marker,
    delete_markers,
    get_markers,
    normalize_marker_color,
)


class TestNormalizeColor:
    def test_exact(self):
        assert normalize_marker_color("Blue") == "Blue"

    def test_case_insensitive(self):
        assert normalize_marker_color("cyan") == "Cyan"
        assert normalize_marker_color("LEMON") == "Lemon"

    def test_whitespace(self):
        assert normalize_marker_color("  Red ") == "Red"

    def test_unknown_raises_with_valid_list(self):
        with pytest.raises(ValueError, match="Valid:"):
            normalize_marker_color("Turquoise")

    def test_all_canonical_roundtrip(self):
        for c in MARKER_COLORS:
            assert normalize_marker_color(c.lower()) == c


class TestAddMarker:
    def test_basic(self, timeline):
        assert add_marker(timeline, 10)
        assert 10 in timeline.GetMarkers()

    def test_color_normalized(self, timeline):
        add_marker(timeline, 10, color="cyan")
        assert timeline.GetMarkers()[10]["color"] == "Cyan"

    def test_occupied_frame_returns_false(self, timeline):
        assert add_marker(timeline, 10)
        assert not add_marker(timeline, 10)

    def test_custom_data_stored(self, timeline):
        add_marker(timeline, 10, custom_data="my-tag")
        assert timeline.GetMarkers()[10]["customData"] == "my-tag"

    def test_rebase_absolute_frame(self, timeline):
        # timeline starts at 90000; an absolute 90100 should land at 100
        add_marker(timeline, 90100, rebase=True)
        assert 100 in timeline.GetMarkers()

    def test_no_rebase_keeps_frame(self, timeline):
        add_marker(timeline, 90100)  # the invisible-marker trap, allowed
        assert 90100 in timeline.GetMarkers()

    def test_timecode_string_input(self, timeline):
        # 01:00:02:00 @ 25fps = absolute 90050 -> relative 50
        add_marker(timeline, "01:00:02:00")
        assert 50 in timeline.GetMarkers()

    def test_bad_color_raises_before_write(self, timeline):
        with pytest.raises(ValueError):
            add_marker(timeline, 10, color="NotAColor")
        assert timeline.GetMarkers() == {}


class TestGetMarkers:
    def _populate(self, timeline):
        add_marker(timeline, 1, color="Blue", note="keep [tag] this")
        add_marker(timeline, 2, color="Red", custom_data="script-a")
        add_marker(timeline, 3, color="Blue", custom_data="script-a")

    def test_all(self, timeline):
        self._populate(timeline)
        assert len(get_markers(timeline)) == 3

    def test_by_color_case_insensitive(self, timeline):
        self._populate(timeline)
        assert sorted(get_markers(timeline, color="blue")) == [1, 3]

    def test_by_note(self, timeline):
        self._populate(timeline)
        assert list(get_markers(timeline, note_contains="[tag]")) == [1]

    def test_by_custom_data_exact(self, timeline):
        self._populate(timeline)
        assert sorted(get_markers(timeline, custom_data="script-a")) == [2, 3]

    def test_combined_filters(self, timeline):
        self._populate(timeline)
        assert list(get_markers(timeline, color="Blue", custom_data="script-a")) == [3]

    def test_empty_timeline(self, timeline):
        assert get_markers(timeline) == {}


class TestDeleteMarkers:
    def _populate(self, timeline):
        add_marker(timeline, 1, color="Blue")
        add_marker(timeline, 2, color="Red", custom_data="tag")
        add_marker(timeline, 3, color="Blue", custom_data="tag")

    def test_no_filter_guard(self, timeline):
        self._populate(timeline)
        with pytest.raises(ValueError, match="ALL"):
            delete_markers(timeline)
        assert len(timeline.GetMarkers()) == 3

    def test_allow_all(self, timeline):
        self._populate(timeline)
        deleted = delete_markers(timeline, allow_all=True)
        assert len(deleted) == 3
        assert timeline.GetMarkers() == {}

    def test_by_custom_data(self, timeline):
        self._populate(timeline)
        deleted = delete_markers(timeline, custom_data="tag")
        assert sorted(deleted) == [2, 3]
        assert list(timeline.GetMarkers()) == [1]

    def test_dry_run_previews_without_deleting(self, timeline):
        self._populate(timeline)
        would = delete_markers(timeline, custom_data="tag", dry_run=True)
        assert sorted(would) == [2, 3]
        assert len(timeline.GetMarkers()) == 3

    def test_predicate(self, timeline):
        self._populate(timeline)
        deleted = delete_markers(timeline, color="Blue",
                                 predicate=lambda f, d: f > 1)
        assert list(deleted) == [3]

    def test_returns_marker_data(self, timeline):
        self._populate(timeline)
        deleted = delete_markers(timeline, custom_data="tag")
        assert deleted[2]["color"] == "Red"
