"""Derived numbers the analytics layer can use."""
from wearables import config
from wearables.models import Reading


def glucose_change(readings: list[Reading], window_minutes: int = 30) -> list[float | None]:
    """Change in glucose (mg/dL) over the last `window_minutes`, per reading."""
    n = window_minutes // config.BUCKET_MINUTES
    out: list[float | None] = []
    for i, r in enumerate(readings):
        prev = readings[i - n] if i >= n else None
        if prev and prev.glucose_mgdl is not None and r.glucose_mgdl is not None:
            out.append(r.glucose_mgdl - prev.glucose_mgdl)
        else:
            out.append(None)
    return out
