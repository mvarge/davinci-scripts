"""Pure unit tests for resolve_kit.timecode (no Resolve required)."""

import pytest

from resolve_kit.timecode import (
    frames_to_timecode,
    is_drop_frame_timecode,
    nominal_fps,
    parse_fps,
    timecode_to_frames,
)


class TestParseFps:
    def test_float(self):
        assert parse_fps(25.0) == 25.0

    def test_int(self):
        assert parse_fps(24) == 24.0

    def test_string(self):
        assert parse_fps("25") == 25.0

    def test_string_decimal(self):
        assert parse_fps("23.976") == 23.976

    def test_string_with_noise(self):
        assert parse_fps(" 29.97 fps") == 29.97

    def test_none_raises(self):
        with pytest.raises(ValueError):
            parse_fps(None)

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_fps("not a rate")

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            parse_fps("0")


class TestNominalFps:
    @pytest.mark.parametrize("real,nominal", [
        (23.976, 24), (23.98, 24), (24.0, 24), (25.0, 25),
        (29.97, 30), (30.0, 30), (50.0, 50), (59.94, 60), (60.0, 60),
    ])
    def test_rates(self, real, nominal):
        assert nominal_fps(real) == nominal


class TestTimecodeRoundtrip:
    @pytest.mark.parametrize("fps", [24.0, 25.0, 30.0, 50.0, 60.0, 23.976, 29.97])
    @pytest.mark.parametrize("frames", [0, 1, 100, 90000, 12_345_678])
    def test_non_drop_roundtrip(self, fps, frames):
        tc = frames_to_timecode(frames, fps)
        assert timecode_to_frames(tc, fps) == frames

    def test_known_values(self):
        assert frames_to_timecode(0, 25) == "00:00:00:00"
        assert frames_to_timecode(25, 25) == "00:00:01:00"
        assert frames_to_timecode(90000, 25) == "01:00:00:00"
        assert timecode_to_frames("01:00:00:00", 25) == 90000

    def test_drop_frame_detection(self):
        assert is_drop_frame_timecode("00:01:00;02")
        assert is_drop_frame_timecode("00:01:00,02")
        assert not is_drop_frame_timecode("00:01:00:02")

    def test_drop_frame_smpte_29_97(self):
        # SMPTE: at 29.97 DF, 00:01:00;02 is the first valid timecode after
        # 00:00:59;29 — frames 0 and 1 of minute 1 are dropped.
        assert timecode_to_frames("00:01:00;02", 29.97) == 1800
        assert frames_to_timecode(1800, 29.97, drop_frame=True) == "00:01:00;02"

    def test_drop_frame_tenth_minute_not_dropped(self):
        # Every 10th minute keeps frames 00/01.
        assert frames_to_timecode(17982, 29.97, drop_frame=True) == "00:10:00;00"
        assert timecode_to_frames("00:10:00;00", 29.97) == 17982

    @pytest.mark.parametrize("frames", [0, 1, 1799, 1800, 17982, 107892])
    def test_drop_frame_roundtrip(self, frames):
        tc = frames_to_timecode(frames, 29.97, drop_frame=True)
        assert timecode_to_frames(tc, 29.97) == frames
