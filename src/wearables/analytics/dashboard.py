"""Data-backed dashboard summaries built from the existing wearable pipeline."""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone

from wearables import config
from wearables.models import Insight, Reading, Sample
from wearables.processing.features import glucose_change

# These bands match the dashboard's existing visual range markers. They are display
# bands for descriptive summaries, not a clinical target recommendation.
DISPLAY_LOW_MGDL = 70.0
DISPLAY_HIGH_MGDL = 180.0
MIN_WINDOW_READINGS = 12  # one hour of data on the five-minute alignment grid

_FALLING_TRENDS = {"fortyFiveDown", "singleDown", "doubleDown"}
_RISING_TRENDS = {"fortyFiveUp", "singleUp", "doubleUp"}


def generate_dashboard_insights(
    readings: list[Reading], event_insights: list[Insight] | None = None,
) -> list[dict]:
    """Return only summaries supported by the supplied glucose readings.

    Long-window cards have minimum sample requirements. Missing dates, events, or
    ranges produce no insight entry; callers may render a truthful empty state.
    """
    valid = [r for r in readings if r.glucose_mgdl is not None]
    if not valid:
        return []

    result: list[dict] = []
    changes = glucose_change(readings)
    latest_valid_index = next((i for i in range(len(readings) - 1, -1, -1)
                               if readings[i].glucose_mgdl is not None), None)
    if latest_valid_index is not None:
        delta = changes[latest_valid_index]
        if delta is not None:
            slope = delta / 30.0
            if abs(slope) < 1.0:
                direction = "stable"
            else:
                direction = "rising" if slope > 0 else "falling"
            result.append(_insight(
                "trend", "Glucose trend",
                f"Glucose was {direction} over the latest 30-minute window "
                f"({delta:+.0f} mg/dL).",
                readings[latest_valid_index].timestamp,
                sample_count=2,
            ))

    for event in event_insights or []:
        result.append(_insight(
            "event", "Significant glucose change", event.message, event.timestamp,
        ))

    if len(valid) >= MIN_WINDOW_READINGS:
        values = [float(r.glucose_mgdl) for r in valid]
        in_range = sum(DISPLAY_LOW_MGDL <= v <= DISPLAY_HIGH_MGDL for v in values)
        pct = 100 * in_range / len(values)
        result.append(_insight(
            "time_in_range", "Time in displayed range",
            f"{pct:.0f}% of {len(values)} available readings were within the "
            f"dashboard's {DISPLAY_LOW_MGDL:.0f}–{DISPLAY_HIGH_MGDL:.0f} mg/dL display band.",
            valid[-1].timestamp, sample_count=len(values), value=round(pct, 1),
        ))

        mean_value = statistics.fmean(values)
        if mean_value > 0:
            cv = 100 * statistics.pstdev(values) / mean_value
            result.append(_insight(
                "variability", "Glucose variability",
                f"The coefficient of variation was {cv:.1f}% across {len(values)} "
                "available readings.",
                valid[-1].timestamp, sample_count=len(values), value=round(cv, 1),
            ))

    by_date: dict[object, list[Reading]] = defaultdict(list)
    recurring: dict[tuple[int, str], dict[object, list[float]]] = defaultdict(lambda: defaultdict(list))
    for reading in valid:
        day = reading.timestamp.date()
        by_date[day].append(reading)
        value = float(reading.glucose_mgdl)
        band = "high" if value > DISPLAY_HIGH_MGDL else "low" if value < DISPLAY_LOW_MGDL else None
        if band:
            recurring[(reading.timestamp.hour, band)][day].append(value)

    qualified_days = [(day, rows) for day, rows in sorted(by_date.items())
                      if len(rows) >= MIN_WINDOW_READINGS]
    if len(qualified_days) >= 2:
        previous_day, previous_rows = qualified_days[-2]
        latest_day, latest_rows = qualified_days[-1]
        previous_mean = statistics.fmean(float(r.glucose_mgdl) for r in previous_rows)
        latest_mean = statistics.fmean(float(r.glucose_mgdl) for r in latest_rows)
        delta = latest_mean - previous_mean
        relation = "higher" if delta > 0 else "lower" if delta < 0 else "unchanged"
        result.append(_insight(
            "daily_comparison", "Daily comparison",
            f"Average glucose on {latest_day.isoformat()} was {abs(delta):.0f} mg/dL "
            f"{relation} than on {previous_day.isoformat()} "
            f"({latest_mean:.0f} vs {previous_mean:.0f} mg/dL).",
            latest_rows[-1].timestamp, sample_count=len(latest_rows) + len(previous_rows),
            value=round(delta, 1),
        ))

    recurring_candidates = []
    for (hour, band), days in recurring.items():
        repeated_days = [(day, vals) for day, vals in days.items() if len(vals) >= 2]
        if len(repeated_days) >= 2:
            recurring_candidates.append((len(repeated_days), hour, band, repeated_days))
    if recurring_candidates:
        count, hour, band, repeated_days = max(recurring_candidates, key=lambda item: (item[0], -item[1]))
        dates = ", ".join(day.isoformat() for day, _ in repeated_days[-3:])
        label = "above 180 mg/dL" if band == "high" else "below 70 mg/dL"
        latest_day, latest_values = repeated_days[-1]
        result.append(_insight(
            "recurring", "Recurring time-of-day pattern",
            f"Readings {label} appeared in the {hour:02d}:00–{hour + 1:02d}:00 UTC hour "
            f"on {count} dates ({dates}).",
            by_date[latest_day][-1].timestamp, sample_count=sum(len(v) for _, v in repeated_days),
        ))

    return result


def generate_pattern_entries(readings: list[Reading], records: list[dict]) -> list[dict]:
    """Group consecutive raw CGM samples into status episodes, retaining source times."""
    if not records:
        return []
    changes = glucose_change(readings)
    index_by_time = {reading.timestamp: i for i, reading in enumerate(readings)}
    items = []
    for record in records:
        original = record.get("timestamp_original")
        timestamp = record.get("timestamp_epoch")
        value = record.get("mgdl")
        if not isinstance(original, str) or not isinstance(timestamp, (int, float)) \
                or not isinstance(value, (int, float)):
            continue
        dt = datetime.fromisoformat(original.replace("Z", "+00:00"))
        # Normalize only for bucket lookup; keep `original` untouched for presentation.
        naive_utc = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        bucket = naive_utc.replace(minute=naive_utc.minute - naive_utc.minute % config.BUCKET_MINUTES,
                                   second=0, microsecond=0)
        row_index = index_by_time.get(bucket)
        delta = changes[row_index] if row_index is not None else None
        status = _status(value, record.get("trend"), delta)
        if status is None:
            continue
        items.append({
            "status": status,
            "description": _pattern_description(status, record.get("trend"), delta, value),
            "mgdl": float(value),
            "timestamp_original": original,
            "timestamp": float(timestamp),
        })

    items.sort(key=lambda item: item["timestamp"])
    episodes = []
    current = []
    for item in items:
        if current and (item["status"] != current[-1]["status"]
                        or item["timestamp"] - current[-1]["timestamp"] > 15 * 60):
            episodes.append(current[-1])
            current = []
        current.append(item)
    if current:
        episodes.append(current[-1])
    episodes.sort(key=lambda item: item["timestamp"], reverse=True)
    return episodes[:250]


def _status(value: float, trend: str | None, delta: float | None) -> str | None:
    if value < DISPLAY_LOW_MGDL:
        return "Low"
    if value > DISPLAY_HIGH_MGDL:
        return "High"
    if trend in _FALLING_TRENDS:
        return "Falling"
    if trend in _RISING_TRENDS:
        return "Rising"
    if trend == "flat":
        return "Stable"
    if delta is None:
        return None
    slope = delta / 30.0
    if slope <= -1.0:
        return "Falling"
    if slope >= 1.0:
        return "Rising"
    return "Stable"


def _pattern_description(status: str, trend: str | None, delta: float | None, value: float) -> str:
    if status == "High":
        return "Reading was above the dashboard's 180 mg/dL display band."
    if status == "Low":
        return "Reading was below the dashboard's 70 mg/dL display band."
    if trend in _FALLING_TRENDS | _RISING_TRENDS | {"flat"}:
        return f"Dexcom trend was {status.lower()} at {value:.0f} mg/dL."
    if delta is not None:
        return f"Glucose changed {delta:+.0f} mg/dL over the preceding 30-minute window."
    return f"Glucose was {status.lower()} at {value:.0f} mg/dL."


def _insight(category: str, title: str, message: str, timestamp: datetime,
             **metadata) -> dict:
    timestamp_utc = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None \
        else timestamp.astimezone(timezone.utc)
    return {
        "category": category,
        "title": title,
        "message": message,
        "timestamp": timestamp_utc.timestamp(),
        "timestamp_original": timestamp.isoformat(),
        **metadata,
    }
