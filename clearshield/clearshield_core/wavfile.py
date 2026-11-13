"""WAV level analysis: bounded RIFF parsing and streaming dBFS measurement.

A dedicated parser is used instead of the stdlib ``wave`` module because
``wave`` accepts only integer PCM, accepts WAVE_FORMAT_EXTENSIBLE only from
Python 3.12, and silently returns fewer frames than a truncated or forged
header declares. ``audioop`` is not used: it was removed in Python 3.13.

Supported: integer PCM 8 (unsigned), 16, 24, 32-bit; IEEE float 32/64-bit;
WAVE_FORMAT_EXTENSIBLE wrapping either; 1-32 channels; 1 Hz-1 MHz.
Not supported: RF64 (>4 GiB), compressed encodings (ADPCM, mu-law, A-law, ...).

Units: dBFS, relative to digital full scale. RMS is referenced so that a
full-scale square wave reads 0 dBFS and a full-scale sine reads -3.01 dBFS.
These are not sound-pressure levels (dB SPL); converting requires a calibrated
microphone and a known gain chain.

Definitions:
  * window RMS = sqrt(mean of squared samples across all channels) / full scale
  * peak = largest absolute sample / full scale
  * clipping run = >= ``clip_run_samples`` consecutive samples on one channel at
    the extreme code values (integer) or with |x| >= 1.0 (float)
  * sustained high level = consecutive windows whose RMS is >= ``sustained_dbfs``
    lasting >= ``sustained_seconds``
  * an all-zero window is "silent"; its level is reported as null, never -inf
"""

from __future__ import annotations

import hashlib
import math
import operator
import os
import stat
import struct
import sys
from array import array
from dataclasses import dataclass
from typing import Any

from .errors import AudioError

FMT_PCM = 0x0001
FMT_FLOAT = 0x0003
FMT_EXTENSIBLE = 0xFFFE
_GUID_TAIL = bytes.fromhex("000010008000" "00aa00389b71")
MAX_CHUNKS = 4096
_INT32 = "i" if array("i").itemsize == 4 else "l"
_BIG = sys.byteorder == "big"


@dataclass
class WavInfo:
    encoding: str  # "pcm" or "float"
    bits: int
    channels: int
    rate: int
    block_align: int
    data_offset: int
    declared_bytes: int
    available_bytes: int

    @property
    def label(self) -> str:
        if self.encoding == "float":
            return f"float{self.bits}le"
        return f"pcm_{'u' if self.bits == 8 else 's'}{self.bits}le"


def _parse_fmt(body: bytes) -> tuple[str, int, int, int, int]:
    tag, channels, rate, _byte_rate, block_align, bits = struct.unpack("<HHIIHH", body[:16])
    if tag == FMT_EXTENSIBLE:
        if len(body) < 40:
            raise AudioError("WAVE_FORMAT_EXTENSIBLE header is too short")
        sub = body[24:40]
        if sub[4:] != _GUID_TAIL:
            raise AudioError("unsupported WAVE_FORMAT_EXTENSIBLE sub-format")
        tag = int.from_bytes(sub[:4], "little")
    if tag == FMT_PCM:
        if bits not in (8, 16, 24, 32):
            raise AudioError(f"unsupported PCM bit depth {bits}; supported: 8, 16, 24, 32")
        encoding = "pcm"
    elif tag == FMT_FLOAT:
        if bits not in (32, 64):
            raise AudioError(f"unsupported float bit depth {bits}; supported: 32, 64")
        encoding = "float"
    else:
        raise AudioError(
            f"unsupported WAV encoding (format tag {tag}); supported: integer PCM "
            "8/16/24/32-bit and IEEE float 32/64-bit"
        )
    if not 1 <= channels <= 32:
        raise AudioError(f"unsupported channel count {channels}; supported: 1-32")
    if not 1 <= rate <= 1_000_000:
        raise AudioError(f"unsupported sample rate {rate} Hz")
    if block_align != channels * bits // 8:
        raise AudioError(
            f"inconsistent header: block_align {block_align} != channels {channels} x {bits // 8} bytes"
        )
    return encoding, bits, channels, rate, block_align


def parse_header(fh: Any, file_size: int) -> WavInfo:
    head = fh.read(12)
    if len(head) < 12:
        raise AudioError("file is too short to be a WAV file")
    if head[:4] == b"RF64":
        raise AudioError("RF64 (WAV larger than 4 GiB) is not supported")
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise AudioError("not a RIFF/WAVE file")
    fmt: tuple[str, int, int, int, int] | None = None
    pos = 12
    for _ in range(MAX_CHUNKS):
        if pos + 8 > file_size:
            break
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            break
        chunk_id, size = header[:4], struct.unpack("<I", header[4:])[0]
        body = pos + 8
        if chunk_id == b"fmt ":
            if not 16 <= size <= 1024:
                raise AudioError(f"fmt chunk has invalid size {size}")
            if body + size > file_size:
                raise AudioError("fmt chunk is truncated")
            fmt = _parse_fmt(fh.read(size))
        elif chunk_id == b"data":
            if fmt is None:
                raise AudioError("data chunk appears before the fmt chunk")
            encoding, bits, channels, rate, block_align = fmt
            available = max(0, min(size, file_size - body))
            return WavInfo(encoding, bits, channels, rate, block_align, body, size, available)
        pos = body + size + (size & 1)
    raise AudioError("no data chunk found" if fmt else "no fmt chunk found")


def scale(info: WavInfo) -> tuple[float, float, float]:
    """(full_scale, high_code, low_code) in the units produced by ``decode``."""
    if info.encoding == "float":
        return 1.0, 1.0, -1.0
    if info.bits == 8:
        return 128.0, 127.0, -128.0
    if info.bits == 16:
        return 32768.0, 32767.0, -32768.0
    # 24-bit samples are widened into the top 3 bytes of a 32-bit word.
    if info.bits == 24:
        return 2.0 ** 31, float((2 ** 23 - 1) << 8), -(2.0 ** 31)
    return 2.0 ** 31, 2.0 ** 31 - 1, -(2.0 ** 31)


def decode(raw: bytes, info: WavInfo) -> array:
    if info.encoding == "float":
        arr = array("f" if info.bits == 32 else "d")
        arr.frombytes(raw)
    elif info.bits == 8:
        return array("h", (b - 128 for b in raw))
    elif info.bits == 16:
        arr = array("h")
        arr.frombytes(raw)
    elif info.bits == 24:
        count = len(raw) // 3
        wide = bytearray(count * 4)
        wide[1::4] = raw[0::3]
        wide[2::4] = raw[1::3]
        wide[3::4] = raw[2::3]
        arr = array(_INT32)
        arr.frombytes(bytes(wide))
    else:
        arr = array(_INT32)
        arr.frombytes(raw)
    if _BIG:
        arr.byteswap()
    return arr


def _db(ratio: float) -> float | None:
    return round(20.0 * math.log10(ratio), 2) if ratio > 0 else None


class LevelMeter:
    """Streaming analysis of interleaved samples, fed one window at a time."""

    def __init__(self, rate: int, channels: int, full_scale: float, high: float, low: float,
                 is_float: bool, clip_run: int, sustained_dbfs: float, sustained_seconds: float) -> None:
        self.rate, self.channels = rate, channels
        self.fs, self.high, self.low, self.is_float = full_scale, high, low, is_float
        self.clip_run, self.sustained_dbfs, self.sustained_seconds = clip_run, sustained_dbfs, sustained_seconds
        self.sumsq = 0.0
        self.samples = 0
        self.frames = 0
        self.peak = 0.0
        self.channel_peak = [0.0] * channels
        self.at_full_scale = 0
        self.nonfinite = 0
        self.runs = 0
        self.samples_in_runs = 0
        self._carry = [0] * channels
        self.windows = 0
        self.silent_windows = 0
        self.max_window_rms_db: float | None = None
        self.segments: list[dict] = []
        self._run_start: float | None = None
        self._run_len = 0.0
        self._run_max = -999.0
        self.t = 0.0

    def _at_extreme(self, x: float) -> bool:
        return x >= self.high or x <= self.low

    def _close_runs(self, channel: int) -> None:
        if self._carry[channel] >= self.clip_run:
            self.runs += 1
            self.samples_in_runs += self._carry[channel]
        self._carry[channel] = 0

    def _close_segment(self) -> None:
        if self._run_start is not None and self._run_len >= self.sustained_seconds:
            self.segments.append({"start_s": round(self._run_start, 3),
                                  "end_s": round(self._run_start + self._run_len, 3),
                                  "max_rms_dbfs": round(self._run_max, 2)})
        self._run_start, self._run_len, self._run_max = None, 0.0, -999.0

    def feed(self, samples: array, frames: int) -> None:
        if self.is_float:
            bad = sum(1 for x in samples if not math.isfinite(x))
            if bad:
                # Zero out NaN/Inf rather than dropping them, to keep channels aligned.
                self.nonfinite += bad
                samples = array("d", (x if math.isfinite(x) else 0.0 for x in samples))
        n = len(samples)
        duration = frames / self.rate
        self.frames += frames
        self.windows += 1
        if n == 0:
            self.t += duration
            return
        if self.is_float:
            sumsq = math.fsum(map(operator.mul, samples, samples))
        else:
            sumsq = float(sum(map(operator.mul, samples, samples)))
        self.sumsq += sumsq
        self.samples += n
        hi, lo = max(samples), min(samples)
        self.peak = max(self.peak, max(hi, -lo) / self.fs)
        if len(samples) % self.channels == 0:
            for c in range(self.channels):
                part = samples[c::self.channels]
                self.channel_peak[c] = max(self.channel_peak[c], max(max(part), -min(part)) / self.fs)

        if hi >= self.high or lo <= self.low:
            if self.is_float:
                self.at_full_scale += sum(1 for x in samples if self._at_extreme(x))
            else:
                self.at_full_scale += samples.count(int(self.high)) + samples.count(int(self.low))
            if len(samples) % self.channels == 0:
                for c in range(self.channels):
                    for x in samples[c::self.channels]:
                        if self._at_extreme(x):
                            self._carry[c] += 1
                        elif self._carry[c]:
                            self._close_runs(c)
        else:
            for c in range(self.channels):
                if self._carry[c]:
                    self._close_runs(c)

        rms = math.sqrt(sumsq / n) / self.fs
        db = _db(rms)
        if db is None:
            self.silent_windows += 1
        elif self.max_window_rms_db is None or db > self.max_window_rms_db:
            self.max_window_rms_db = db
        if db is not None and db >= self.sustained_dbfs:
            if self._run_start is None:
                self._run_start = self.t
            self._run_len += duration
            self._run_max = max(self._run_max, db)
        else:
            self._close_segment()
        self.t += duration

    def finish(self) -> dict[str, Any]:
        for c in range(self.channels):
            self._close_runs(c)
        self._close_segment()
        rms = math.sqrt(self.sumsq / self.samples) / self.fs if self.samples else 0.0
        return {
            "frames_analysed": self.frames,
            "duration_s": round(self.frames / self.rate, 3),
            "levels": {
                "peak_dbfs": _db(self.peak),
                "rms_dbfs": _db(rms),
                "silent": self.samples > 0 and self.sumsq == 0,
                "channel_peak_dbfs": [_db(p) for p in self.channel_peak],
            },
            "windows": {"count": self.windows, "silent": self.silent_windows,
                        "max_rms_dbfs": self.max_window_rms_db},
            "clipping": {"clip_run_samples": self.clip_run, "runs": self.runs,
                         "samples_in_runs": self.samples_in_runs,
                         "samples_at_full_scale": self.at_full_scale},
            "sustained_high": {"threshold_dbfs": self.sustained_dbfs,
                               "min_seconds": self.sustained_seconds, "segments": self.segments},
            "nonfinite_samples": self.nonfinite,
        }


UNITS_NOTE = ("dBFS relative to digital full scale (full-scale sine RMS = -3.01 dBFS). "
              "Not dB SPL: no acoustic calibration is applied.")


def findings_from(summary: dict, subject: str) -> list[dict]:
    findings: list[dict] = []
    sustained = summary["sustained_high"]
    if sustained["segments"]:
        findings.append({"layer": "audio", "kind": "sustained_high_level", "severity": "medium",
                         "file": subject,
                         "detail": {"segments": sustained["segments"][:50],
                                    "threshold_dbfs": sustained["threshold_dbfs"],
                                    "min_seconds": sustained["min_seconds"],
                                    "note": "high digital level; says nothing about the source or intent"}})
    clip = summary["clipping"]
    if clip["runs"]:
        findings.append({"layer": "audio", "kind": "clipping_detected", "severity": "low",
                         "file": subject, "detail": dict(clip)})
    if summary.get("truncated"):
        findings.append({"layer": "audio", "kind": "audio_truncated", "severity": "low",
                         "file": subject,
                         "detail": {"declared_frames": summary.get("declared_frames"),
                                    "frames_present": summary.get("frames_present"),
                                    "note": "header declares more audio than the file contains"}})
    if summary.get("partial"):
        findings.append({"layer": "audio", "kind": "audio_partially_analysed", "severity": "low",
                         "file": subject, "detail": {"note": "stopped at audio.max_seconds"}})
    if summary.get("nonfinite_samples"):
        findings.append({"layer": "audio", "kind": "nonfinite_samples", "severity": "low",
                         "file": subject, "detail": {"count": summary["nonfinite_samples"]}})
    return findings


def analyze_file(path: str, audio_cfg: dict) -> tuple[dict, list[dict]]:
    """Analyse one WAV file. Raises AudioError for unusable input. Writes nothing."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise AudioError(f"{path}: file not found") from None
    except OSError as exc:
        raise AudioError(f"{path}: cannot open ({exc.strerror})") from None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise AudioError(f"{path}: not a regular file")
        if st.st_size > audio_cfg["max_bytes"]:
            raise AudioError(f"{path}: {st.st_size} bytes exceeds audio.max_bytes ({audio_cfg['max_bytes']})")
        info = parse_header(fh, st.st_size)
        frames_present = info.available_bytes // info.block_align
        max_frames = int(audio_cfg["max_seconds"] * info.rate)
        to_read = min(frames_present, max_frames)
        window = max(1, info.rate * audio_cfg["window_ms"] // 1000)
        full, high, low = scale(info)
        meter = LevelMeter(info.rate, info.channels, full, high, low, info.encoding == "float",
                           audio_cfg["clip_run_samples"], audio_cfg["sustained_dbfs"],
                           audio_cfg["sustained_seconds"])
        fh.seek(info.data_offset)
        remaining = to_read
        while remaining > 0:
            frames = min(window, remaining)
            raw = fh.read(frames * info.block_align)
            frames = len(raw) // info.block_align
            if frames == 0:
                break
            meter.feed(decode(raw[: frames * info.block_align], info), frames)
            remaining -= frames
        digest = hashlib.sha256()
        fh.seek(0)
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fh.fileno())
    summary = meter.finish()
    declared = info.declared_bytes // info.block_align
    summary.update({
        "file": os.path.abspath(path),
        "sha256": digest.hexdigest(),
        "changed_during_analysis": (after.st_size, after.st_mtime_ns) != (st.st_size, st.st_mtime_ns),
        "format": {"encoding": info.label, "channels": info.channels,
                   "sample_rate": info.rate, "bits": info.bits},
        "declared_frames": declared,
        "frames_present": frames_present,
        "truncated": info.available_bytes < info.declared_bytes,
        "partial": frames_present > max_frames,
        "window_ms": audio_cfg["window_ms"],
        "units": UNITS_NOTE,
    })
    return summary, findings_from(summary, summary["file"])
