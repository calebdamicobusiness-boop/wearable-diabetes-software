"""Fake but realistic-looking data so everything can be built and tested now."""
import math
import random
from datetime import datetime, timedelta
from typing import Iterator

from wearables import config
from wearables.models import Sample


class MockSource:
    def __init__(self, start: datetime | None = None, hours: int = 24, seed: int = 1):
        self.start = start or datetime(2026, 1, 1, 0, 0)
        self.hours = hours
        self.rng = random.Random(seed)

    def samples(self) -> Iterator[Sample]:
        minutes = self.hours * 60
        meals = [7 * 60 + 30, 12 * 60 + 30, 18 * 60 + 30]  # minutes after midnight
        for m in range(0, minutes, 5):
            t = self.start + timedelta(minutes=m)
            tod = m % (24 * 60)
            sleeping = tod < 6 * 60 or tod >= 23 * 60

            glucose = 100 + self.rng.gauss(0, 2)
            for meal in meals:
                dt = tod - meal
                if 0 <= dt <= 180:
                    glucose += 90 * math.sin(math.pi * dt / 180)
            hr = (55 if sleeping else 72) + self.rng.gauss(0, 3)
            steps = 0 if sleeping else max(0, int(self.rng.gauss(60, 80)))
            if 17 * 60 <= tod < 17 * 60 + 45:  # evening workout
                hr += 50
                steps += 400

            yield Sample(t, config.GLUCOSE, round(glucose, 1))
            yield Sample(t, config.HEART_RATE, round(hr, 1))
            yield Sample(t, config.SKIN_TEMP, round(33 + self.rng.gauss(0, 0.2), 2))
            yield Sample(t, config.STEPS, steps)
            yield Sample(t, config.SLEEPING, 1.0 if sleeping else 0.0)
