#!/usr/bin/env python3
"""Fixed-window per-key rate limiter (stdlib, in-process).

Deliberately simple: a fixed window is dumb on purpose — the real abuse
protection is the upstream disk cache (repeat requests never reach
Commons), this is just a soft flood guard.

Caveat (documented in README): each gunicorn worker keeps its own
counter, so with N workers the effective limit is N x the configured
limit. Fine for a soft guard; a shared store (SQLite) would be the
next step if exactness ever matters.
"""
import threading
import time


class RateLimiter:
    def __init__(self, limit, window=60.0, max_keys=8192):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self._hits = {}          # key -> (window_start, count)
        self._lock = threading.Lock()

    def allow(self, key):
        """True if the request is under the limit (and record it)."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > self.max_keys:
                cutoff = now - self.window
                self._hits = {k: v for k, v in self._hits.items()
                              if v[0] > cutoff}
            w0, n = self._hits.get(key, (now, 0))
            if now - w0 >= self.window:
                w0, n = now, 0
            if n >= self.limit:
                return False
            self._hits[key] = (w0, n + 1)
            return True

    def retry_after(self, key):
        """Seconds until the current window rolls over (for Retry-After)."""
        now = time.monotonic()
        with self._lock:
            w0, _ = self._hits.get(key, (now, 0))
            return max(1, int(self.window - (now - w0)) + 1)
