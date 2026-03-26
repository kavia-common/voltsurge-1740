from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.sessions import ProcessedResult


def _decode_csv_bytes(raw_bytes: bytes) -> str:
    # Prefer UTF-8; gracefully handle BOM.
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    return text


def _try_parse_datetime(s: str) -> Optional[datetime]:
    s = (s or "").strip()
    if not s:
        return None

    # Basic ISO handling; support trailing 'Z'.
    try:
        if s.endswith("Z") and "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _normalize_unit_to_kwh_multiplier(unit_raw: str) -> Optional[float]:
    """Return multiplier to convert given unit to kWh (energy_kwh = value * multiplier)."""
    u = (unit_raw or "").strip().lower()
    if not u:
        return None

    # Normalize common variations.
    u = u.replace(" ", "").replace("_", "").replace("-", "")
    if u in {"kwh", "kilowatthour", "kilowatthours", "kwhr", "kwhrs"}:
        return 1.0
    if u in {"wh", "watthour", "watthours", "whr", "whrs"}:
        return 1.0 / 1000.0
    if u in {"mwh", "megawatthour", "megawatthours"}:
        return 1000.0

    return None


def _to_float(value: str) -> Optional[float]:
    s = (value or "").strip()
    if not s:
        return None
    # Remove thousands separators if present.
    s = s.replace(",", "")
    try:
        x = float(s)
    except Exception:
        return None
    if not math.isfinite(x):
        return None
    return x


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for it in items:
        key = (it.get("timestamp"), round(float(it.get("energy_kwh")), 12))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _sort_by_timestamp(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Sort by parsed datetime when possible; fallback to raw timestamp string.
    def sort_key(it: Dict[str, Any]) -> Tuple[int, Any]:
        ts = str(it.get("timestamp") or "")
        dt = _try_parse_datetime(ts)
        if dt is None:
            return (1, ts)
        return (0, dt)

    return sorted(items, key=sort_key)


def _compute_stats(values: List[float]) -> Tuple[float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0)
    total = float(sum(values))
    min_v = float(min(values))
    max_v = float(max(values))
    return total, min_v, max_v


# PUBLIC_INTERFACE
def process_csv_bytes(
    raw_bytes: bytes,
    timestamp_col: str,
    energy_col: str,
    unit_col: str,
) -> ProcessedResult:
    """Parse and process CSV bytes into cleaned datapoints, baseline, and anomalies.

    Args:
        raw_bytes: Raw uploaded CSV file bytes.
        timestamp_col: Name of timestamp column.
        energy_col: Name of energy value column.
        unit_col: Name of unit column.

    Returns:
        ProcessedResult: Cleaned time-series, stats, and anomalies.

    Raises:
        ValueError: If CSV is invalid, columns are missing, or no valid rows remain.
    """
    text = _decode_csv_bytes(raw_bytes)
    reader = csv.DictReader(text.splitlines())

    if reader.fieldnames is None:
        raise ValueError("CSV appears to have no header row.")

    fieldnames = [f.strip() for f in reader.fieldnames if f is not None]
    for col in (timestamp_col, energy_col, unit_col):
        if col not in fieldnames:
            raise ValueError(f"Missing required column: {col}")

    rows_received = 0
    cleaned: List[Dict[str, Any]] = []

    for row in reader:
        rows_received += 1

        ts_raw = (row.get(timestamp_col) or "").strip()
        energy_raw = (row.get(energy_col) or "").strip()
        unit_raw = (row.get(unit_col) or "").strip()

        dt = _try_parse_datetime(ts_raw)
        if dt is None:
            # If cannot parse, still allow raw string but require non-empty; however sorting may degrade.
            if not ts_raw:
                continue

        energy = _to_float(energy_raw)
        if energy is None:
            continue

        mult = _normalize_unit_to_kwh_multiplier(unit_raw)
        if mult is None:
            continue

        energy_kwh = energy * mult
        if not math.isfinite(energy_kwh):
            continue

        cleaned.append(
            {
                "timestamp": ts_raw,
                "energy_kwh": float(energy_kwh),
            }
        )

    if not cleaned:
        raise ValueError("No valid rows after cleaning. Check your column mapping and units.")

    cleaned = _dedupe(cleaned)
    cleaned = _sort_by_timestamp(cleaned)

    values = [float(r["energy_kwh"]) for r in cleaned]
    rows_cleaned = len(cleaned)
    baseline = float(sum(values) / rows_cleaned) if rows_cleaned else 0.0

    threshold = baseline * 1.2
    anomalies: List[Dict[str, Any]] = []
    anomaly_ts = set()

    for r in cleaned:
        e = float(r["energy_kwh"])
        if e > threshold:
            ratio = float(e / baseline) if baseline > 0 else float("inf")
            anomalies.append(
                {
                    "timestamp": r["timestamp"],
                    "energy_kwh": e,
                    "baseline_avg_kwh": baseline,
                    "threshold_kwh": threshold,
                    "ratio": ratio,
                }
            )
            anomaly_ts.add(r["timestamp"])

    # Add convenience flag to datapoints (frontend can also use /anomalies timestamps).
    data_points = []
    for r in cleaned:
        data_points.append(
            {
                "timestamp": r["timestamp"],
                "energy_kwh": float(r["energy_kwh"]),
                "is_anomaly": r["timestamp"] in anomaly_ts,
            }
        )

    total, min_v, max_v = _compute_stats(values)

    return ProcessedResult(
        rows_received=rows_received,
        rows_cleaned=rows_cleaned,
        baseline_avg_kwh=baseline,
        total_energy_kwh=total,
        min_energy_kwh=min_v,
        max_energy_kwh=max_v,
        data_points=data_points,
        anomalies=anomalies,
    )
