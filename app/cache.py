"""Tiny invalidation-based cache for the dashboard sidebar data.

The sidebar polls every 2s per open tab. Recomputing ``dashboard_data`` (which
scans all active videos + groups) on every poll is wasteful, so we cache the
result and only recompute when state actually changes. Any code that mutates
videos/groups calls :func:`bump`; the next read recomputes, otherwise the
cached value is returned with no DB work.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_version = 0          # bumped on every state change
_cached_version = -1  # version the cached value reflects
_cached_data = None


def bump() -> None:
    """Signal that dashboard-relevant state changed; invalidates the cache."""
    global _version
    with _lock:
        _version += 1


def get_dashboard_data() -> dict:
    """Return cached dashboard data, recomputing only when state changed."""
    global _cached_data, _cached_version
    # Imported lazily to avoid import cycles at module load.
    from . import queries
    from .db import get_session

    with _lock:
        version = _version
        if _cached_data is not None and _cached_version == version:
            return _cached_data

    # Compute outside the lock so DB work doesn't serialise other readers.
    with get_session() as session:
        data = queries.dashboard_data(session)

    with _lock:
        # Tag with the version captured *before* computing; if another bump
        # landed meanwhile, the next read will recompute.
        _cached_data = data
        _cached_version = version
    return data
