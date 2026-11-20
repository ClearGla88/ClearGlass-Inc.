"""Request signing shared by sensors and the ingestion API.

Signature: HMAC-SHA256 over "v1\\n<sensor>\\n<unix-seconds>\\n<nonce>\\n<sha256(body)>".
The timestamp bounds replay to the clock-skew window; the nonce closes it.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

SENSOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
TIMESTAMP_RE = re.compile(r"^\d{9,11}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SIGNATURE_RE = re.compile(r"^v1=[0-9a-f]{64}$")

HEADER_SENSOR = "X-CG-Sensor"
HEADER_TIMESTAMP = "X-CG-Timestamp"
HEADER_NONCE = "X-CG-Nonce"
HEADER_SIGNATURE = "X-CG-Signature"


def signing_input(sensor_id: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return f"v1\n{sensor_id}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()


def sign(key: bytes, sensor_id: str, timestamp: str, nonce: str, body: bytes) -> str:
    return "v1=" + hmac.new(key, signing_input(sensor_id, timestamp, nonce, body), hashlib.sha256).hexdigest()


def verify(key: bytes, sensor_id: str, timestamp: str, nonce: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(key, sensor_id, timestamp, nonce, body), signature)


def signed_headers(key: bytes, sensor_id: str, body: bytes, *, unix_time: int, nonce: str | None = None) -> dict:
    nonce = nonce or secrets.token_urlsafe(24)
    ts = str(int(unix_time))
    return {
        HEADER_SENSOR: sensor_id,
        HEADER_TIMESTAMP: ts,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: sign(key, sensor_id, ts, nonce, body),
        "Content-Type": "application/json",
    }
