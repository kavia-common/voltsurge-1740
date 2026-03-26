from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar
from copy import deepcopy

T = TypeVar("T")


@dataclass(frozen=True)
class StoreStats:
    """Simple stats snapshot for the in-memory store."""

    sessions_count: int
    ttl_seconds: int
    max_sessions: int


class StoreKeyNotFoundError(KeyError):
    """Raised when a key is missing from the in-memory store."""


class InMemorySessionStore(Generic[T]):
    """Thread-safe in-memory store keyed by session_id with TTL and max-sessions eviction.

    Design goals:
    - CRUD operations
    - Strict per-session isolation: callers cannot mutate the store's internal state through
      returned objects. We enforce this by deep-copying on get/list and on set.
    - Simple expiry/eviction policy:
        * TTL expiry based on last_access monotonic time
        * Capacity eviction: when exceeding max_sessions, evict least-recently-accessed

    Notes:
    - This store is meant for ephemeral, single-process runtime storage.
    - It does NOT provide cross-process consistency (no DB).
    """

    def __init__(self, ttl_seconds: int = 60 * 60, max_sessions: int = 250) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be > 0")

        self._ttl_seconds = int(ttl_seconds)
        self._max_sessions = int(max_sessions)

        self._lock = threading.Lock()
        # key -> (value, created_at_monotonic, last_access_monotonic)
        self._items: Dict[str, Tuple[T, float, float]] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _is_expired(self, last_access: float, now: float) -> bool:
        return (now - last_access) > self._ttl_seconds

    def _prune_expired_locked(self, now: float) -> int:
        """Remove expired items. Must be called under lock."""
        expired_keys = [k for k, (_, _, last) in self._items.items() if self._is_expired(last, now)]
        for k in expired_keys:
            del self._items[k]
        return len(expired_keys)

    def _evict_if_needed_locked(self, now: float) -> int:
        """Evict least-recently-accessed until within capacity. Must be called under lock."""
        evicted = 0
        while len(self._items) > self._max_sessions:
            # Choose least-recently-accessed
            lru_key = min(self._items.items(), key=lambda kv: kv[1][2])[0]
            del self._items[lru_key]
            evicted += 1
        return evicted

    def _maybe_housekeep_locked(self, now: float) -> Tuple[int, int]:
        expired = self._prune_expired_locked(now)
        evicted = self._evict_if_needed_locked(now)
        return expired, evicted

    # PUBLIC_INTERFACE
    def set(self, key: str, value: T) -> None:
        """Create or replace a session value.

        Args:
            key: Session key (session_id).
            value: Value to store.

        Returns:
            None
        """
        now = self._now()
        with self._lock:
            self._maybe_housekeep_locked(now)
            self._items[key] = (deepcopy(value), now, now)
            self._evict_if_needed_locked(now)

    # PUBLIC_INTERFACE
    def create(self, key: str, value: T) -> None:
        """Create a session value. Fails if key already exists.

        Args:
            key: Session key (session_id).
            value: Value to store.

        Raises:
            ValueError: If key already exists.
        """
        now = self._now()
        with self._lock:
            self._maybe_housekeep_locked(now)
            if key in self._items:
                raise ValueError(f"Key already exists: {key}")
            self._items[key] = (deepcopy(value), now, now)
            self._evict_if_needed_locked(now)

    # PUBLIC_INTERFACE
    def get(self, key: str) -> T:
        """Get a session value by key.

        Enforces per-session isolation by returning a deep copy.

        Args:
            key: Session key (session_id).

        Returns:
            The stored value.

        Raises:
            StoreKeyNotFoundError: If key is missing or expired.
        """
        now = self._now()
        with self._lock:
            self._maybe_housekeep_locked(now)
            item = self._items.get(key)
            if not item:
                raise StoreKeyNotFoundError(f"Session not found: {key}")
            value, created, _last = item
            # touch
            self._items[key] = (value, created, now)
            return deepcopy(value)

    # PUBLIC_INTERFACE
    def delete(self, key: str) -> None:
        """Delete a session by key.

        Args:
            key: Session key (session_id).

        Raises:
            StoreKeyNotFoundError: If key is missing (or expired).
        """
        now = self._now()
        with self._lock:
            self._maybe_housekeep_locked(now)
            if key not in self._items:
                raise StoreKeyNotFoundError(f"Session not found: {key}")
            del self._items[key]

    # PUBLIC_INTERFACE
    def clear(self) -> int:
        """Clear all sessions.

        Returns:
            int: Number of sessions removed.
        """
        with self._lock:
            n = len(self._items)
            self._items.clear()
        return n

    # PUBLIC_INTERFACE
    def list_keys(self, limit: int = 10) -> List[str]:
        """List up to `limit` keys in a stable order (most-recently-accessed first).

        Args:
            limit: Maximum keys to return.

        Returns:
            List[str]: Session keys (session_ids).
        """
        now = self._now()
        with self._lock:
            self._maybe_housekeep_locked(now)
            # Sort by last_access descending
            keys = sorted(self._items.items(), key=lambda kv: kv[1][2], reverse=True)
            return [k for k, _ in keys[: max(0, int(limit))]]

    # PUBLIC_INTERFACE
    def stats(self) -> StoreStats:
        """Return store stats snapshot (also triggers housekeeping).

        Returns:
            StoreStats: sessions_count, ttl_seconds, max_sessions
        """
        now = self._now()
        with self._lock:
            self._maybe_housekeep_locked(now)
            return StoreStats(
                sessions_count=len(self._items),
                ttl_seconds=self._ttl_seconds,
                max_sessions=self._max_sessions,
            )


# PUBLIC_INTERFACE
def build_default_session_store() -> InMemorySessionStore[Any]:
    """Build the default session store instance using environment overrides.

    Environment variables (optional):
      - VOLTSURGE_SESSION_TTL_SECONDS: int, default 3600
      - VOLTSURGE_MAX_SESSIONS: int, default 250

    Returns:
        InMemorySessionStore[Any]: configured store.
    """
    ttl = int(os.getenv("VOLTSURGE_SESSION_TTL_SECONDS", "3600") or "3600")
    max_sessions = int(os.getenv("VOLTSURGE_MAX_SESSIONS", "250") or "250")
    return InMemorySessionStore(ttl_seconds=ttl, max_sessions=max_sessions)
