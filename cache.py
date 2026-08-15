#!/usr/bin/env python3
"""Tiny stdlib disk cache for the Reframe proxy.

Stores opaque byte blobs keyed by string — one file per key
(sha1 hex + ".bin") with an atomic-replace write, so concurrent
processes (gunicorn workers) never observe torn entries.

Expiry is enforced two ways:

  - per-read: the entry header carries its own ttl, checked against
    mtime (so a short-lived negative-cached 404 expires even if no
    sweep has run)
  - lazy sweep: every N puts, delete files older than max_ttl, then
    evict oldest-by-mtime until the directory is under max_bytes

Corrupt entries are treated as misses (never crash the request path).
"""
import hashlib
import json
import os
import threading
import time

_HEADER = b"META"


class DiskCache:
    def __init__(self, directory, max_bytes=2 * 1024 ** 3,
                 max_ttl=7 * 24 * 3600, sweep_every=64):
        self.dir = directory
        self.max_bytes = max_bytes      # evict-oldest cap
        self.max_ttl = max_ttl          # default per-entry ttl; also sweep cutoff
        self.sweep_every = sweep_every
        self._puts = 0
        self._lock = threading.Lock()
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, key):
        return os.path.join(
            self.dir, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".bin")

    def get(self, key):
        """Return (status, body) or None on miss / expired / corrupt."""
        path = self._path(key)
        try:
            with open(path, "rb") as f:
                data = f.read()
            meta, body = _unpack(data)
        except Exception:
            return None  # missing, torn, or corrupt — treat as a miss
        if time.time() - os.path.getmtime(path) > meta["t"]:
            return None  # expired; lazy sweep will reclaim the file
        return meta["s"], body

    def put(self, key, body, status=200, content_type="", ttl=None):
        """Store an entry atomically. ttl defaults to max_ttl."""
        ttl = self.max_ttl if ttl is None else ttl
        path = self._path(key)
        tmp = path + f".tmp{os.getpid()}"
        with open(tmp, "wb") as f:
            f.write(_pack(status, content_type, ttl, body))
        os.replace(tmp, path)  # atomic on POSIX — readers never see a torn file
        self._maybe_sweep()

    def stats(self):
        """Approx {entries, bytes} — for request logging / ops."""
        n = total = 0
        try:
            for e in os.scandir(self.dir):
                if e.is_file():
                    n += 1
                    total += e.stat().st_size
        except OSError:
            pass
        return {"entries": n, "bytes": total}

    # -- internals --------------------------------------------------------- #

    def _maybe_sweep(self):
        with self._lock:
            self._puts += 1
            if self._puts % self.sweep_every:
                return
        self._sweep()

    def _sweep(self):
        """Delete entries older than max_ttl, then evict oldest-by-mtime
        until the directory is under max_bytes. Best-effort: races with
        concurrent writers are harmless (worst case a stale entry lingers
        until the next sweep)."""
        try:
            entries = [(e.stat().st_mtime, e.path) for e in os.scandir(self.dir)
                       if e.is_file()]
        except OSError:
            return
        now = time.time()
        entries = [e for e in entries if now - e[0] <= self.max_ttl]
        total = 0
        for _, path in entries:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        if total <= self.max_bytes:
            return
        for _mtime, path in sorted(entries):  # oldest first
            if total <= self.max_bytes:
                break
            try:
                total -= os.path.getsize(path)
                os.unlink(path)
            except OSError:
                pass


def _pack(status, content_type, ttl, body):
    meta = json.dumps({"s": status, "ct": content_type, "t": ttl},
                      separators=(",", ":"))
    return _HEADER + meta.encode("utf-8") + b"\n" + body


def _unpack(data):
    nl = data.index(b"\n")
    meta = json.loads(data[len(_HEADER):nl].decode("utf-8"))
    return meta, data[nl + 1:]
