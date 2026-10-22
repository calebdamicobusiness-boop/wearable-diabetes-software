"""Rule-based placeholder analytics. Replace or extend with real models later.

Wording is about awareness ("glucose rose after..."), never diagnosis or dosing.
"""
from wearables import config
from wearables.models import Insight, Reading
from wearables.processing.features import glucose_change


def generate_insights(readings: list[Reading]) -> list[Insight]:
    insights: list[Insight] = []
    changes = glucose_change(readings)
    last_rise = last_drop = None  # avoid spamming one insight per bucket
    for r, delta in zip(readings, changes):
        if delta is None:
            continue
        if delta >= config.RAPID_RISE_MGDL_PER_30MIN and (
            last_rise is None or (r.timestamp - last_rise).total_seconds() > 3600
        ):
            insights.append(Insight(r.timestamp, "rise",
                                    f"Glucose rose about {delta:.0f} mg/dL in 30 minutes."))
            last_rise = r.timestamp
        elif delta <= config.RAPID_DROP_MGDL_PER_30MIN and (
            last_drop is None or (r.timestamp - last_drop).total_seconds() > 3600
        ):
            active = (r.steps or 0) >= config.ACTIVE_STEPS_PER_BUCKET
            extra = " during higher activity." if active else "."
            insights.append(Insight(r.timestamp, "drop",
                                    f"Glucose fell about {abs(delta):.0f} mg/dL in 30 minutes{extra}"))
            last_drop = r.timestamp
    return insights
