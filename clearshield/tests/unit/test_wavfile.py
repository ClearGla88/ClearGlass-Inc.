"""WAV parsing and level analysis (unit). Expected dBFS values were cross-checked
against an independent stdlib reference before this implementation existed."""

from __future__ import annotations

import json
import math
import struct

import pytest

from clearshield_core.config import default_config
from clearshield_core.errors import AudioError
from clearshield_core.wavfile import analyze_file
from cs_testlib import tone

AUDIO = default_config()["audio"]


def analyse(path, **overrides):
    cfg = dict(AUDIO)
    cfg.update(overrides)
    return analyze_file(path, cfg)


def test_silence_reports_null_levels_not_infinity(wav):
    summary, findings = analyse(wav([0.0] * 8000))
    assert summary["levels"] == {"peak_dbfs": None, "rms_dbfs": None, "silent": True,
                                 "channel_peak_dbfs": [None]}
    assert summary["windows"]["silent"] == 1
    assert findings == []
    json.dumps(summary, allow_nan=False)  # must be strict-JSON serialisable


def test_tone_levels_match_reference_values(wav):
    # amplitude 16000/32768, 1 kHz: reference peak -6.23 dBFS, RMS -9.24 dBFS
    summary, findings = analyse(wav(tone(1000, 16000 / 32768, 1.0, 8000)))
    assert summary["levels"]["peak_dbfs"] == pytest.approx(-6.23, abs=0.01)
    assert summary["levels"]["rms_dbfs"] == pytest.approx(-9.24, abs=0.02)
    assert summary["format"] == {"encoding": "pcm_s16le", "channels": 1, "sample_rate": 8000, "bits": 16}
    assert findings == []


@pytest.mark.parametrize("bits,encoding,extensible", [
    (8, "pcm", False), (16, "pcm", False), (24, "pcm", False), (32, "pcm", False),
    (32, "float", False), (64, "float", False), (16, "pcm", True), (24, "pcm", True), (32, "float", True),
])
def test_all_supported_formats_agree(wav, bits, encoding, extensible):
    samples = tone(500, 0.5, 0.5, 8000)
    summary, _ = analyse(wav(samples, bits=bits, encoding=encoding, extensible=extensible))
    expected_rms = 20 * math.log10(0.5 / math.sqrt(2))
    tolerance = 0.3 if bits == 8 else 0.02
    assert summary["levels"]["rms_dbfs"] == pytest.approx(expected_rms, abs=tolerance)
    assert summary["frames_analysed"] == 4000


def test_eight_bit_is_unsigned(wav):
    # 8-bit WAV stores silence as 128; treating it as signed would read near full scale.
    path = wav(data=bytes([128] * 800), bits=8)
    summary, _ = analyse(path)
    assert summary["levels"]["silent"] is True


def test_sustained_high_level_detected(wav):
    summary, findings = analyse(wav(tone(440, 0.5, 12.0, 8000)))  # RMS ~ -9 dBFS for 12 s
    segments = summary["sustained_high"]["segments"]
    assert len(segments) == 1 and segments[0]["start_s"] == 0.0
    assert segments[0]["end_s"] == pytest.approx(12.0)
    assert [f["kind"] for f in findings] == ["sustained_high_level"]


def test_short_loud_burst_is_not_sustained(wav):
    summary, findings = analyse(wav(tone(440, 0.5, 5.0, 8000)))
    assert summary["sustained_high"]["segments"] == []
    assert findings == []


def test_quiet_tone_below_threshold_is_not_sustained(wav):
    summary, _ = analyse(wav(tone(440, 0.05, 12.0, 8000)))  # about -29 dBFS
    assert summary["sustained_high"]["segments"] == []


def test_clipped_sine_detected_as_runs(wav):
    summary, findings = analyse(wav(tone(100, 1.5, 1.0, 8000)))  # hard-clipped at full scale
    clip = summary["clipping"]
    assert clip["runs"] > 0 and clip["samples_in_runs"] >= clip["runs"] * 3
    assert "clipping_detected" in [f["kind"] for f in findings]


def test_isolated_full_scale_samples_are_not_clipping(wav):
    # 2 kHz at 8 kHz: 0, +FS, 0, -FS ... every full-scale sample stands alone
    samples = [0.0, 1.0, 0.0, -1.0] * 2000
    summary, findings = analyse(wav(samples))
    assert summary["clipping"]["samples_at_full_scale"] == 4000
    assert summary["clipping"]["runs"] == 0
    assert findings == []


def test_clip_run_across_window_boundary_counted_once(wav):
    samples = [0.0] * 7998 + [1.0] * 4 + [0.0] * 7998  # run straddles the 8000-frame window edge
    summary, _ = analyse(wav(samples))
    assert summary["clipping"]["runs"] == 1
    assert summary["clipping"]["samples_in_runs"] == 4


def test_stereo_channel_peaks(wav):
    samples = []
    for i in range(8000):
        samples += [0.5 * math.sin(2 * math.pi * 440 * i / 8000), 0.0]
    summary, _ = analyse(wav(samples, channels=2))
    left, right = summary["levels"]["channel_peak_dbfs"]
    assert left == pytest.approx(-6.02, abs=0.05) and right is None


def test_truncated_file_flagged(wav, tmp_path):
    full = tone(440, 0.3, 1.0, 8000)
    path = wav(full)
    raw = open(path, "rb").read()
    cut = tmp_path / "cut.wav"
    cut.write_bytes(raw[:200])
    summary, findings = analyse(str(cut))
    assert summary["truncated"] is True
    assert summary["declared_frames"] == 8000 and summary["frames_present"] == (200 - 44) // 2
    assert "audio_truncated" in [f["kind"] for f in findings]


def test_forged_size_header_does_not_drive_reads(wav):
    path = wav(data=b"\x10\x00" * 50, declared_data_bytes=0xFFFFFFE0)
    summary, findings = analyse(path)
    assert summary["frames_analysed"] == 50
    assert summary["declared_frames"] == 0xFFFFFFE0 // 2
    assert "audio_truncated" in [f["kind"] for f in findings]


def test_odd_sized_chunk_before_data_is_skipped_with_padding(wav):
    path = wav(tone(440, 0.5, 0.25, 8000), extra_chunks=[(b"LIST", b"abc")])
    summary, _ = analyse(path)
    assert summary["frames_analysed"] == 2000


def test_zero_length_data(wav):
    summary, findings = analyse(wav(data=b""))
    assert summary["frames_analysed"] == 0
    assert summary["levels"]["silent"] is False and summary["levels"]["rms_dbfs"] is None
    assert findings == []


def test_nan_float_samples_counted_and_ignored(wav):
    data = struct.pack("<4f", 0.5, float("nan"), -0.5, float("inf"))
    summary, findings = analyse(wav(data=data, bits=32, encoding="float"))
    assert summary["nonfinite_samples"] == 2
    json.dumps(summary, allow_nan=False)
    assert "nonfinite_samples" in [f["kind"] for f in findings]


@pytest.mark.parametrize("kwargs,message", [
    ({"data": b"", "riff_id": b"RF64"}, "RF64"),
    ({"data": b"\x00" * 10, "format_tag": 7, "bits": 8}, "format tag 7"),
    ({"data": b"\x00" * 10, "bits": 12}, "bit depth 12"),
    ({"data": b"\x00" * 10, "encoding": "float", "bits": 16}, "float bit depth 16"),
])
def test_unsupported_inputs_rejected_with_reason(wav, kwargs, message):
    with pytest.raises(AudioError, match=message):
        analyse(wav(**kwargs))


def test_not_a_wav(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"this is not audio at all")
    with pytest.raises(AudioError, match="not a RIFF/WAVE"):
        analyse(str(bad))


def test_too_short(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"RIFF")
    with pytest.raises(AudioError, match="too short"):
        analyse(str(bad))


def test_inconsistent_block_align_rejected(tmp_path):
    fmt = struct.pack("<HHIIHH", 1, 2, 8000, 32000, 3, 16)  # block_align should be 4
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", 4) + b"\x00" * 4
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    with pytest.raises(AudioError, match="block_align"):
        analyse(str(bad))


def test_size_limit_enforced(wav):
    path = wav(tone(440, 0.5, 1.0, 8000))
    with pytest.raises(AudioError, match="exceeds audio.max_bytes"):
        analyse(path, max_bytes=1000)


def test_duration_limit_marks_partial(wav):
    summary, findings = analyse(wav(tone(440, 0.1, 3.0, 8000)), max_seconds=1)
    assert summary["partial"] is True and summary["frames_analysed"] == 8000
    assert "audio_partially_analysed" in [f["kind"] for f in findings]


def test_fifo_is_rejected_without_blocking(tmp_path):
    import os
    fifo = tmp_path / "pipe.wav"
    os.mkfifo(fifo)
    with pytest.raises(AudioError, match="not a regular file"):
        analyse(str(fifo))


def test_missing_file(tmp_path):
    with pytest.raises(AudioError, match="not found"):
        analyse(str(tmp_path / "absent.wav"))
