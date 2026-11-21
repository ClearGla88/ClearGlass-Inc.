"""Optional live-microphone level analysis. Off by default; two-step opt-in.

The microphone is opened only by the ``audio-live`` command, only when
``audio.live.enabled`` is true in config.json AND ``--allow-microphone`` is
passed, and only for a bounded number of seconds. Samples are analysed in
memory one window at a time and discarded. Nothing is written to disk except
the summary record in the audit log.

Requires the optional ``sounddevice`` package (PortAudio bindings). Its raw
stream class returns bytes, so NumPy is not needed. This adapter has been
exercised with a simulated stream in the test suite, not against real
microphone hardware.

Limits: operating-system input paths may apply automatic gain or noise
suppression, so levels are not comparable across devices or sessions, and are
never sound-pressure levels. A muted or disconnected device delivers digital
silence; an all-zero session is reported as a suspected missing signal path,
not as a quiet environment.
"""

from __future__ import annotations

from array import array
from typing import Any, Callable, Protocol

from .errors import AudioError
from .report import sanitize
from .wavfile import UNITS_NOTE, LevelMeter, findings_from


class InputStream(Protocol):
    def read(self, frames: int) -> tuple[Any, bool]: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


StreamFactory = Callable[[Any, int, int, int], InputStream]


def open_sounddevice(device: Any, rate: int, channels: int, block_frames: int) -> InputStream:
    try:
        import sounddevice  # type: ignore[import-not-found]
    except (ImportError, OSError) as exc:
        # On Linux, sounddevice raises OSError at import when the system PortAudio
        # library is missing (verified in sounddevice 0.5.6 source).
        raise AudioError(
            "live audio needs the optional 'sounddevice' package and the system PortAudio "
            f"library ({sanitize(exc, 200)}). See README.md, 'Optional live audio'."
        ) from None
    stream = sounddevice.RawInputStream(samplerate=rate, channels=channels, dtype="float32",
                                        device=device, blocksize=block_frames)
    stream.start()
    return stream


def run_live(seconds: float, audio_cfg: dict, device: Any = None,
             stream_factory: StreamFactory = open_sounddevice) -> tuple[dict, list[dict]]:
    live = audio_cfg["live"]
    rate, channels = live["sample_rate"], live["channels"]
    window = max(1, rate * audio_cfg["window_ms"] // 1000)
    meter = LevelMeter(rate, channels, 1.0, 1.0, -1.0, True, audio_cfg["clip_run_samples"],
                       audio_cfg["sustained_dbfs"], audio_cfg["sustained_seconds"])
    subject = f"microphone:{sanitize(device if device is not None else 'default', 80)}"
    findings: list[dict] = []
    target = int(seconds * rate)
    captured = 0
    overflows = 0
    try:
        stream = stream_factory(device, rate, channels, window)
    except AudioError:
        raise
    except Exception as exc:  # PortAudio raises its own error types
        findings.append({"layer": "audio", "kind": "microphone_unavailable", "severity": "medium",
                         "file": subject, "detail": {"error": sanitize(exc, 300)}})
        return {"device": subject, "frames_analysed": 0, "duration_s": 0.0}, findings
    try:
        while captured < target:
            frames = min(window, target - captured)
            buf, overflowed = stream.read(frames)
            samples = array("f")
            samples.frombytes(bytes(buf))
            meter.feed(samples, frames)
            captured += frames
            overflows += 1 if overflowed else 0
            del samples, buf  # nothing is kept beyond the current window
    except Exception as exc:
        findings.append({"layer": "audio", "kind": "microphone_lost", "severity": "medium",
                         "file": subject,
                         "detail": {"error": sanitize(exc, 300),
                                    "seconds_captured": round(captured / rate, 3)}})
    finally:
        for action in ("stop", "close"):
            try:
                getattr(stream, action)()
            except Exception:
                pass
    summary = meter.finish()
    summary.update({"device": subject, "sample_rate": rate, "channels": channels,
                    "input_overflows": overflows, "units": UNITS_NOTE,
                    "raw_audio_retained": False})
    if captured and summary["levels"]["silent"]:
        findings.append({"layer": "audio", "kind": "no_signal_path_suspected", "severity": "medium",
                         "file": subject,
                         "detail": {"note": "every sample was digital zero: the device may be muted, "
                                            "disconnected, or blocked. This is not evidence of a quiet room."}})
    findings.extend(findings_from(summary, subject))
    return summary, findings
