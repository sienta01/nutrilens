import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RedactSecrets(logging.Filter):
    """Rewrite known secrets out of records. Attach to any logger or handler that writes them."""

    def __init__(self, *values: str):
        super().__init__()
        self.values = [value for value in values if value]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.values:
            message = record.getMessage()
            clean = message
            for value in self.values:
                clean = clean.replace(value, "[REDACTED]")
            if clean != message:
                # Collapse to a literal message; the arguments are already interpolated.
                record.msg = clean
                record.args = ()
        return True


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


class RateLimiter:
    """Single-process sliding windows. Put shared rate limiting in front of replicas."""

    def __init__(self):
        self.entries = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str, limit: int, window: int = 60):
        now = time.monotonic()
        with self.lock:
            # Evict inactive keys as well as timestamps to bound long-lived memory.
            if len(self.entries) > 5000:
                for old_key in list(self.entries):
                    if not self.entries[old_key] or self.entries[old_key][-1] < now - 3600:
                        del self.entries[old_key]
            bucket = self.entries[key]
            while bucket and bucket[0] < now - window:
                bucket.popleft()
            if len(bucket) >= limit:
                raise HTTPException(429, "Too many requests. Please try again shortly.", headers={"Retry-After": str(window)})
            bucket.append(now)
