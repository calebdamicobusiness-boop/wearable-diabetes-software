"""Turn a FusedWindow into the plain dict a dashboard (server.py -> app.js) can show.

Descriptive only (S4): words like "steady" or "rising", never "good", "bad", "high" or "low"
as judgments, and the awareness note always travels with the data.
"""
from datetime import datetime, timezone
from typing import Optional

from sensor_integration import DEFAULT_GLUCOSE_UNIT, MGDL_PER_MMOLL, FusedWindow, format_glucose

_DEXCOM_TREND = {
    "doubleUp": "rising quickly", "singleUp": "rising", "fortyFiveUp": "rising slowly",
    "flat": "steady",
    "fortyFiveDown": "falling slowly", "singleDown": "falling", "doubleDown": "falling quickly",
}


def trend_from_slope(slope_mgdl_per_min: float) -> str:
    """Same bands Dexcom documents for its arrows (flat is within +/-1 mg/dL per minute)."""
    a = abs(slope_mgdl_per_min)
    if a < 1:
        return "steady"
    word = "slowly" if a < 2 else ("" if a < 3 else "quickly")
    return " ".join(x for x in ("rising" if slope_mgdl_per_min > 0 else "falling", word) if x)


def dashboard_payload(w: FusedWindow, unit: str = DEFAULT_GLUCOSE_UNIT,
                      last_record: Optional[dict] = None) -> dict:
    out: dict = {
        "window": {"status": w.status, "missing_pct": round(100 * w.missing_frac),
                   "confidence": round(w.confidence, 2)},
        "note": w.note,
        "glucose": {"state": "none", "text": "No glucose reading available."},
    }
    if w.glucose_last_mgdl is not None:
        stale = bool(w.glucose_is_stale())
        value = w.glucose_last_mgdl if unit == "mg/dL" else w.glucose_last_mgdl / MGDL_PER_MMOLL
        trend = None
        if not stale:                                   # an old trend would mislead
            if last_record and last_record.get("trend") in _DEXCOM_TREND:
                trend = _DEXCOM_TREND[last_record["trend"]]
            elif "glucose_slope_per_min" in w.features:
                trend = trend_from_slope(w.features["glucose_slope_per_min"])
        status = (last_record or {}).get("status")
        out["glucose"] = {
            "state": "stale" if stale else "current",
            "value": round(value, 1 if unit == "mmol/L" else 0),
            "unit": unit,
            "text": format_glucose(w.glucose_last_mgdl, unit),
            "timestamp_utc": datetime.fromtimestamp(w.glucose_last_t, timezone.utc).isoformat(),
            "age_min": round(w.glucose_age_s() / 60),
            "trend": trend,
            # "high"/"low" = outside the sensor's measuring range; shown as a plain fact
            "out_of_sensor_range": status if status in ("high", "low") else None,
        }
    f = w.features
    if "pct_in_range" in f:
        out["range"] = {k: round(f[k]) for k in ("pct_in_range", "pct_below_range", "pct_above_range")}
    return out