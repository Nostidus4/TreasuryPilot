"""Primary-key ids shared by the services (DATA_MODEL: UUIDv7, time-ordered)."""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate a time-ordered UUIDv7 without requiring a pre-3.14 backport."""

    timestamp_ms = time.time_ns() // 1_000_000
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= random_a << 64
    value |= 0b10 << 62
    value |= random_b
    return uuid.UUID(int=value)
