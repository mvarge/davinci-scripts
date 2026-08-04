"""Unit tests for export_beat_subtitles (no Resolve required).

Covers signature parsing, bar collection from marker dicts, beat subdivision
arithmetic, SRT rendering/timecode rebasing, and the gap/overlap validator.
"""

import importlib.util
import pathlib

import pytest

# Loaded by path because the script lives at the repo root, not in a package.
_SPEC = importlib.util.spec_from_file_location(
    "export_beat_subtitles",
    pathlib.Path(__file__).resolve().parent.parent / "export_beat_subtitles.py",
)
ebs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ebs)

Bar = ebs.Bar
Caption = ebs.Caption


class TestParseSignature:
    def test_simple(self):
        assert ebs.parse_signature("6/4") == (6, 4)

    def test_eighths(self):
        assert ebs.parse_signature("5/8") == (5, 8)

    def test_whitespace_tolerated(self):
        assert ebs.parse_signature("  7 / 4 ") == (7, 4)

    @pytest.mark.parametrize("name", ["", "intro", "chorus 6/4", "6", "6/", "/4", "x/y", None])
    def test_rejects_non_signatures(self, name):
        assert ebs.parse_signature(name) is None

    @pytest.mark.parametrize("name", ["0/4", "6/0", "0/0"])
    def test_rejects_zero(self, name):
        """A 0-beat bar cannot be subdivided; a 0 denominator is not a note value."""
        assert ebs.parse_signature(name) is None


class TestCollectBars:
    def test_pairs_consecutive_markers(self):
        markers = {
            0: {"name": "6/4", "note": ""},
            100: {"name": "5/4", "note": ""},
            180: {"name": "4/4", "note": ""},
        }
        bars = ebs.collect_bars(markers)
        assert bars == [Bar(0, 100, 6, 4), Bar(100, 180, 5, 4)]

    def test_last_marker_produces_no_bar(self):
        """The final marker only terminates the previous bar."""
        bars = ebs.collect_bars({0: {"name": "4/4", "note": ""}, 80: {"name": "4/4", "note": ""}})
        assert len(bars) == 1

    def test_single_marker_yields_nothing(self):
        assert ebs.collect_bars({0: {"name": "4/4", "note": ""}}) == []

    def test_empty(self):
        assert ebs.collect_bars({}) == []

    def test_skips_generated_beat_markers(self):
        """Sub-markers from create_beat_markers.py must not be read as bars."""
        markers = {
            0: {"name": "6/4", "note": ""},
            50: {"name": "3/6", "note": ebs.GENERATED_MARKER_NOTE},
            100: {"name": "5/4", "note": ""},
            200: {"name": "4/4", "note": ""},
        }
        assert ebs.collect_bars(markers) == [Bar(0, 100, 6, 4), Bar(100, 200, 5, 4)]

    def test_ignores_unrelated_marker_names(self):
        markers = {
            0: {"name": "6/4", "note": ""},
            40: {"name": "guitar solo", "note": ""},
            100: {"name": "5/4", "note": ""},
            200: {"name": "4/4", "note": ""},
        }
        assert ebs.collect_bars(markers) == [Bar(0, 100, 6, 4), Bar(100, 200, 5, 4)]

    def test_sorts_unordered_markers(self):
        """GetMarkers() returns a dict; insertion order is not frame order."""
        markers = {
            200: {"name": "4/4", "note": ""},
            0: {"name": "6/4", "note": ""},
            100: {"name": "5/4", "note": ""},
        }
        assert [b.start for b in ebs.collect_bars(markers)] == [0, 100]

    def test_missing_note_key_tolerated(self):
        assert ebs.collect_bars({0: {"name": "4/4"}, 80: {"name": "4/4"}}) == [Bar(0, 80, 4, 4)]


class TestBeatFrames:
    def test_even_division(self):
        assert ebs.beat_frames(Bar(0, 120, 6, 4)) == [
            (0, 20), (20, 40), (40, 60), (60, 80), (80, 100), (100, 120)
        ]

    def test_remainder_pushed_to_end(self):
        """106/6 = 17 r4, so the last 4 intervals get 18. Matches
        create_beat_markers.py so captions land on its markers."""
        spans = ebs.beat_frames(Bar(0, 106, 6, 4))
        assert [e - s for s, e in spans] == [17, 17, 18, 18, 18, 18]

    def test_is_contiguous_and_exact(self):
        """No gaps, and the last beat lands exactly on the bar end."""
        for total in range(4, 200):
            for num in (3, 4, 5, 6, 7):
                spans = ebs.beat_frames(Bar(10, 10 + total, num, 4))
                assert len(spans) == num
                assert spans[0][0] == 10
                assert spans[-1][1] == 10 + total
                for earlier, later in zip(spans, spans[1:]):
                    assert earlier[1] == later[0]

    def test_beat_count_equals_numerator(self):
        assert len(ebs.beat_frames(Bar(0, 45, 5, 8))) == 5
        assert len(ebs.beat_frames(Bar(0, 62, 7, 8))) == 7

    def test_single_beat_bar(self):
        assert ebs.beat_frames(Bar(0, 25, 1, 4)) == [(0, 25)]


class TestCaptions:
    def test_signature_caption_spans_whole_bar(self):
        captions = ebs.build_signature_captions([Bar(0, 106, 6, 4)])
        assert captions == [Caption(0, 106, "6/4")]

    def test_beat_captions_use_bar_denominator(self):
        """A 5/8 bar counts in eighths, not as '1/5'."""
        texts = [c.text for c in ebs.build_beat_captions([Bar(0, 45, 5, 8)])]
        assert texts == ["1/8", "2/8", "3/8", "4/8", "5/8"]

    def test_quarter_bar_counts_in_quarters(self):
        texts = [c.text for c in ebs.build_beat_captions([Bar(0, 120, 6, 4)])]
        assert texts == ["1/4", "2/4", "3/4", "4/4", "5/4", "6/4"]

    def test_two_line_layout(self):
        captions = ebs.build_beat_captions([Bar(0, 120, 6, 4)], with_signature=True)
        assert captions[0].text == "6/4\n1/4"
        assert captions[2].text == "6/4\n3/4"

    def test_two_line_denominators_always_agree(self):
        for bar in (Bar(0, 45, 5, 8), Bar(0, 106, 6, 4), Bar(0, 62, 7, 8)):
            for caption in ebs.build_beat_captions([bar], with_signature=True):
                sig, beat = caption.text.split("\n")
                assert sig.split("/")[1] == beat.split("/")[1]

    def test_two_tracks_share_bar_boundaries(self):
        """ST1 bar starts must coincide with an ST2 beat-1 start, or the two
        tracks drift apart on screen."""
        bars = [Bar(0, 106, 6, 4), Bar(106, 194, 5, 4), Bar(194, 239, 5, 8)]
        sig_starts = {c.start for c in ebs.build_signature_captions(bars)}
        beat_starts = {c.start for c in ebs.build_beat_captions(bars)}
        assert sig_starts <= beat_starts

    def test_no_captions_without_bars(self):
        assert ebs.build_beat_captions([]) == []
        assert ebs.build_signature_captions([]) == []


class TestCli:
    def test_default_layout_is_two_line(self):
        """Only one subtitle track is visible at a time (manual p. 1268), so the
        default must be the single-track two-line layout, never two-track."""
        assert ebs.build_parser().parse_args([]).layout == "two-line"

    def test_all_layouts_accepted(self):
        for layout in ("two-line", "beats-only", "two-track"):
            assert ebs.build_parser().parse_args(["--layout", layout]).layout == layout

    def test_unknown_layout_rejected(self):
        with pytest.raises(SystemExit):
            ebs.build_parser().parse_args(["--layout", "two-tracks"])

    def test_dry_run_defaults_off(self):
        assert ebs.build_parser().parse_args([]).dry_run is False


class TestSrtTimestamp:
    def test_zero(self):
        assert ebs.srt_timestamp(0, 50.0) == "00:00:00,000"

    def test_sub_second_frames(self):
        assert ebs.srt_timestamp(25, 50.0) == "00:00:00,500"

    def test_whole_seconds(self):
        assert ebs.srt_timestamp(100, 50.0) == "00:00:02,000"

    def test_hours(self):
        assert ebs.srt_timestamp(180000, 50.0) == "01:00:00,000"

    def test_25fps(self):
        assert ebs.srt_timestamp(30, 25.0) == "00:00:01,200"

    def test_millis_never_overflow(self):
        """Rounding must not emit ',1000'."""
        for fps in (23.976, 24.0, 25.0, 29.97, 50.0, 59.94):
            for frame in range(0, 400):
                assert int(ebs.srt_timestamp(frame, fps).split(",")[1]) <= 999


class TestRenderSrt:
    def test_rebases_relative_frames_to_absolute(self):
        """Marker frames are timeline-relative; SRT needs absolute timecode."""
        text = ebs.render_srt([Caption(0, 50, "1/4")], 50.0, timeline_start=180000)
        assert "01:00:00,000 --> 01:00:01,000" in text

    def test_block_structure(self):
        text = ebs.render_srt([Caption(0, 50, "1/4"), Caption(50, 100, "2/4")], 50.0, 0)
        blocks = text.strip().split("\n\n")
        assert len(blocks) == 2
        assert blocks[0].split("\n")[0] == "1"
        assert blocks[1].split("\n")[0] == "2"
        assert blocks[0].split("\n")[2] == "1/4"

    def test_two_line_text_preserved(self):
        text = ebs.render_srt([Caption(0, 50, "6/4\n1/4")], 50.0, 0)
        assert text.strip().split("\n")[2:4] == ["6/4", "1/4"]

    def test_end_to_end_is_gapless(self):
        markers = {
            0: {"name": "6/4", "note": ""},
            106: {"name": "5/8", "note": ""},
            151: {"name": "4/4", "note": ""},
        }
        captions = ebs.build_beat_captions(ebs.collect_bars(markers))
        assert ebs.validate(captions) == []
        assert len(captions) == 6 + 5


class TestValidate:
    def test_clean(self):
        assert ebs.validate([Caption(0, 50, "a"), Caption(50, 100, "b")]) == []

    def test_detects_overlap(self):
        problems = ebs.validate([Caption(0, 60, "a"), Caption(50, 100, "b")])
        assert any("overlap" in p for p in problems)

    def test_detects_gap(self):
        problems = ebs.validate([Caption(0, 40, "a"), Caption(50, 100, "b")])
        assert any("gap" in p for p in problems)

    def test_detects_zero_duration(self):
        problems = ebs.validate([Caption(10, 10, "a")])
        assert any("non-positive" in p for p in problems)

    def test_empty_is_clean(self):
        assert ebs.validate([]) == []


class TestSummarize:
    def test_counts_meters_and_tempo(self):
        summary = ebs.summarize([Bar(0, 106, 6, 4), Bar(106, 212, 6, 4)], 50.0)
        assert "2 bars" in summary
        assert "6/4 x2" in summary
        assert "BPM" in summary

    def test_no_bars(self):
        assert ebs.summarize([], 50.0) == "no bars"
