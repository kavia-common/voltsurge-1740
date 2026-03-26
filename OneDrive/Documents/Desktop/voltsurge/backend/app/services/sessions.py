from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.services.in_memory_store import (
    InMemorySessionStore,
    StoreKeyNotFoundError,
    build_default_session_store,
)


class SessionNotFoundError(KeyError):
    """Raised when a session_id is missing from the in-memory store."""


@dataclass(frozen=True)
class ProcessedResult:
    """Processed dataset results for a session."""

    rows_received: int
    rows_cleaned: int
    baseline_avg_kwh: float
    total_energy_kwh: float
    min_energy_kwh: float
    max_energy_kwh: float
    data_points: List[Dict[str, Any]]
    anomalies: List[Dict[str, Any]]


@dataclass(frozen=True)
class Session:
    """Represents a single in-memory processing session.

    Note: This dataclass is treated as immutable from the store's perspective. The store returns
    deep-copies to ensure callers cannot mutate internal stored state.
    """

    session_id: str
    created_at: str
    rows_received: int
    rows_cleaned: int
    baseline_avg_kwh: float
    total_energy_kwh: float
    min_energy_kwh: float
    max_energy_kwh: float
    data_points: List[Dict[str, Any]]
    anomalies: List[Dict[str, Any]]

    def summary_dict(self) -> Dict[str, Any]:
        """Return a dict compatible with the frontend summary expectations."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "rows_received": self.rows_received,
            "rows_cleaned": self.rows_cleaned,
            "baseline_avg_kwh": self.baseline_avg_kwh,
            "anomalies_count": len(self.anomalies),
            "total_energy_kwh": self.total_energy_kwh,
            "min_energy_kwh": self.min_energy_kwh,
            "max_energy_kwh": self.max_energy_kwh,
        }


_store: InMemorySessionStore[Session] = build_default_session_store()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# PUBLIC_INTERFACE
def create_session(result: ProcessedResult) -> Session:
    """Create and store a new session from processed results.

    Args:
        result: ProcessedResult containing cleaned data, anomalies, and stats.

    Returns:
        Session: Created session instance.
    """
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        created_at=_utc_now_iso(),
        rows_received=result.rows_received,
        rows_cleaned=result.rows_cleaned,
        baseline_avg_kwh=result.baseline_avg_kwh,
        total_energy_kwh=result.total_energy_kwh,
        min_energy_kwh=result.min_energy_kwh,
        max_energy_kwh=result.max_energy_kwh,
        data_points=result.data_points,
        anomalies=result.anomalies,
    )
    _store.set(session_id, session)
    return session


# PUBLIC_INTERFACE
def get_session(session_id: str) -> Session:
    """Retrieve a session by id.

    Args:
        session_id: Session identifier.

    Returns:
        Session: Stored session.

    Raises:
        SessionNotFoundError: If not found (or expired/evicted).
    """
    try:
        return _store.get(session_id)
    except StoreKeyNotFoundError as e:
        raise SessionNotFoundError(str(e)) from e


# PUBLIC_INTERFACE
def delete_session(session_id: str) -> None:
    """Delete a session by id.

    Args:
        session_id: Session identifier.

    Raises:
        SessionNotFoundError: If not found (or expired/evicted).
    """
    try:
        _store.delete(session_id)
    except StoreKeyNotFoundError as e:
        raise SessionNotFoundError(str(e)) from e


# PUBLIC_INTERFACE
def clear_all_sessions() -> int:
    """Delete all sessions.

    Returns:
        int: Number of sessions deleted.
    """
    return _store.clear()


# PUBLIC_INTERFACE
def list_sessions_preview(limit: int = 10) -> Dict[str, Any]:
    """Return a small preview list of sessions for debugging.

    Args:
        limit: Max number of session IDs to include.

    Returns:
        Dict[str, Any]: Preview information.
    """
    ids = _store.list_keys(limit=limit)
    stats = _store.stats()
    return {
        "sessions_count": stats.sessions_count,
        "session_ids_preview": ids,
        "store_policy": {"ttl_seconds": stats.ttl_seconds, "max_sessions": stats.max_sessions},
    }
