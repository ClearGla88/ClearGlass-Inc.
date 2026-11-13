"""Test helpers: synthetic WAV builder and config editing. Imported by tests and conftest."""

from __future__ import annotations

import json
import math
import os
import struct

PCM_GUID_TAIL = bytes.fromhex("000010008000" "00aa00389b71")


def tone(freq: float, amplitude: float, seconds: float, rate: int, channels: int = 1) -> list[float]:
    """Interleaved float samples in [-amplitude, amplitude]."""
    frames = int(seconds * rate)
    out = []
    for i in range(frames):
        value = amplitude * math.sin(2 * math.pi * freq * i / rate)
        out.extend([value] * channels)
    return out


def encode_samples(samples: list[float], bits: int, encoding: str) -> bytes:
    if encoding == "float":
        return struct.pack(f"<{len(samples)}{'f' if bits == 32 else 'd'}", *samples)
    full = 2 ** (bits - 1)
    out = bytearray()
    for x in samples:
        v = max(-full, min(full - 1, int(round(x * full))))
        if bits == 8:
            out.append(v + 128)
        else:
            out += v.to_bytes(bits // 8, "little", signed=True)
    return bytes(out)


def build_wav(samples: list[float] | None = None, *, rate: int = 8000, channels: int = 1, bits: int = 16,
              encoding: str = "pcm", extensible: bool = False, data: bytes | None = None,
              declared_data_bytes: int | None = None, format_tag: int | None = None,
              extra_chunks: list[tuple[bytes, bytes]] | None = None, riff_id: bytes = b"RIFF") -> bytes:
    payload = data if data is not None else encode_samples(samples or [], bits, encoding)
    block = channels * bits // 8
    tag = format_tag if format_tag is not None else (3 if encoding == "float" else 1)
    if extensible:
        sub = struct.pack("<I", tag) + PCM_GUID_TAIL
        fmt_body = struct.pack("<HHIIHH", 0xFFFE, channels, rate, rate * block, block, bits)
        fmt_body += struct.pack("<HHI", 22, bits, 4 if channels == 1 else 3) + sub
    else:
        fmt_body = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    chunks = b"fmt " + struct.pack("<I", len(fmt_body)) + fmt_body
    for cid, body in extra_chunks or []:
        chunks += cid + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) % 2 else b"")
    size = len(payload) if declared_data_bytes is None else declared_data_bytes
    chunks += b"data" + struct.pack("<I", size) + payload
    body = b"WAVE" + chunks
    return riff_id + struct.pack("<I", min(len(body), 0xFFFFFFFF)) + body


def set_config(state_dir: str, **sections: dict) -> None:
    """Merge overrides into config.json (call before 'baseline' to avoid a config-change finding)."""
    path = os.path.join(state_dir, "config.json")
    with open(path) as fh:
        cfg = json.load(fh)
    for section, values in sections.items():
        for key, value in values.items():
            if isinstance(value, dict):
                cfg[section].setdefault(key, {}).update(value)
            else:
                cfg[section][key] = value
    with open(path, "w") as fh:
        json.dump(cfg, fh)
