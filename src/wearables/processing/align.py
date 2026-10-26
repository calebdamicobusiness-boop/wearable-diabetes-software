"""Turn messy per-sensor samples into one clean time grid."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from wearables import config
from wearables.models import Reading, Sample


def _bucket(ts: datetime, minutes: int) -> datetime:
    return ts.replace(minute=ts.minute - ts.minute % minutes, second=0, microsecond=0)


def align(samples: Iterable[Sample], minutes: int = config.BUCKET_MINUTES) -> list[Reading]:
    groups: dict[datetime, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for s in samples:
        groups[_bucket(s.timestamp, minutes)][s.signal].append(s.value)
    if not groups:
        return []

    readings = []
    t, end = min(groups), max(groups)
    while t <= end:  # include empty buckets so gaps are visible as None
        sig = groups.get(t, {})
        mean = lambda name: sum(sig[name]) / len(sig[name]) if sig.get(name) else None
        steps = sum(sig[config.STEPS]) if sig.get(config.STEPS) else None
        sleeping = (mean(config.SLEEPING) >= 0.5) if sig.get(config.SLEEPING) else None
        readings.append(Reading(
            timestamp=t,
            glucose_mgdl=mean(config.GLUCOSE),
            heart_rate_bpm=mean(config.HEART_RATE),
            skin_temp_c=mean(config.SKIN_TEMP),
            steps=int(steps) if steps is not None else None,
            sleeping=sleeping,
        ))
        t += timedelta(minutes=minutes)
    return readings
