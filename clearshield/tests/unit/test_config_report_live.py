"""Configuration validation, output escaping, live-audio adapter (unit).

The live adapter is driven by a simulated stream. No microphone is opened."""

from __future__ import annotations

import json
import math
import struct

import pytest

from clearshield_core import audio_live, config, report
from clearshield_core.errors import ConfigError


# ------------------------------------------------------------------ config

def write_cfg(tmp_path, body):
    d = tmp_path / "s"
    d.mkdir(mode=0o700)
    p = d / "config.json"
    p.write_text(json.dumps(body))
    p.chmod(0o600)
    return str(d)


def test_defaults_are_conservative():
    c = config.default_config()
    assert c["audio"]["live"]["enabled"] is False
    assert c["auth"]["record_invalid_usernames"] is False
    config.validate(c)


def test_sample_config_matches_code_defaults():
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "clearshield.example.json")
    with open(path) as fh:
        sample = json.load(fh)
    sample.pop("_comment")
    assert sample == config.default_config()


def test_partial_override_merges(tmp_path):
    cfg, sha = config.load_config(write_cfg(tmp_path, {"auth": {"failure_threshold": 3}}))
    assert cfg["auth"]["failure_threshold"] == 3 and cfg["auth"]["window_seconds"] == 600
    assert len(sha) == 64


@pytest.mark.parametrize("body,message", [
    ({"auth": {"failure_treshold": 3}}, "unknown configuration key: auth.failure_treshold"),
    ({"auth": {"failure_threshold": 0}}, "outside"),
    ({"auth": {"failure_threshold": True}}, "must be a number"),
    ({"audio": {"sustained_dbfs": 3}}, "outside"),
    ({"audio": {"live": {"enabled": "yes"}}}, "true or false"),
    ({"auth": {"sources": ["file:relative"]}}, "file:/absolute/path"),
    ({"listeners": {"allow": [22]}}, "list of strings"),
    ({"auth": []}, "must be an object"),
])
def test_invalid_config_rejected(tmp_path, body, message):
    with pytest.raises(ConfigError, match=message):
        config.load_config(write_cfg(tmp_path, body))


def test_group_writable_config_rejected(tmp_path):
    d = write_cfg(tmp_path, {})
    (tmp_path / "s" / "config.json").chmod(0o620)
    with pytest.raises(Exception, match="chmod 600"):
        config.load_config(d)


# ------------------------------------------------------------------ report

@pytest.mark.parametrize("raw,expected", [
    ("plain", "plain"),
    ("\x1b[2J", "\\x1b[2J"),
    ("a\nb\rc", "a\\x0ab\\x0dc"),
    ("evil‮gnp.exe", "evil\\u202egnp.exe"),
    ("café", "café"),
])
def test_sanitize(raw, expected):
    assert report.sanitize(raw) == expected


def test_sanitize_truncates():
    assert report.sanitize("x" * 10, 4) == "xxxx..."


def test_exit_code_ignores_info():
    assert not report.actionable([{"severity": "info"}])
    assert report.actionable([{"severity": "info"}, {"severity": "low"}])


# ------------------------------------------------------------------ live audio (simulated)

class FakeStream:
    def __init__(self, blocks, fail_after=None):
        self.blocks, self.fail_after, self.reads, self.closed = blocks, fail_after, 0, False

    def read(self, frames):
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise RuntimeError("Stream is stopped: device unavailable")
        value = self.blocks(self.reads, frames)
        self.reads += 1
        return struct.pack(f"<{frames}f", *value), False

    def stop(self):
        pass

    def close(self):
        self.closed = True


def live_cfg():
    c = config.default_config()["audio"]
    c["live"]["sample_rate"] = 8000
    return c


def loud(index, frames):
    return [0.5 * math.sin(2 * math.pi * 440 * (index * frames + i) / 8000) for i in range(frames)]


def test_live_loud_input_flags_sustained_level_and_retains_nothing():
    stream = FakeStream(loud)
    summary, findings = audio_live.run_live(12, live_cfg(), None, lambda *a: stream)
    assert stream.closed and summary["raw_audio_retained"] is False
    assert summary["duration_s"] == 12.0
    assert "sustained_high_level" in [f["kind"] for f in findings]
    assert len(json.dumps(summary)) < 4096  # aggregates only, no sample data


def test_live_all_zero_input_is_suspected_missing_signal_path():
    summary, findings = audio_live.run_live(2, live_cfg(), None, lambda *a: FakeStream(lambda i, n: [0.0] * n))
    assert [f["kind"] for f in findings] == ["no_signal_path_suspected"]
    assert "not evidence of a quiet room" in findings[0]["detail"]["note"]


def test_live_device_lost_mid_session():
    stream = FakeStream(loud, fail_after=3)
    summary, findings = audio_live.run_live(10, live_cfg(), None, lambda *a: stream)
    lost = [f for f in findings if f["kind"] == "microphone_lost"]
    assert lost and lost[0]["detail"]["seconds_captured"] == 3.0 and stream.closed


def test_live_device_unavailable():
    def factory(*a):
        raise RuntimeError("Error querying device -1")

    summary, findings = audio_live.run_live(5, live_cfg(), None, factory)
    assert [f["kind"] for f in findings] == ["microphone_unavailable"]
    assert summary["frames_analysed"] == 0


def test_missing_sounddevice_gives_install_guidance(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "sounddevice":
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Exception, match="optional 'sounddevice' package"):
        audio_live.open_sounddevice(None, 8000, 1, 800)


def test_missing_portaudio_library_gives_install_guidance(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Exception, match="system PortAudio library"):
        audio_live.open_sounddevice(None, 8000, 1, 800)
