"""Data shapes shared by every part of the pipeline."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Sample:
    """One raw measurement from any sensor."""
    timestamp: datetime
    signal: str      # one of the names in config.py
    value: float


@dataclass
class Reading:
    """All signals lined up on one time bucket. None = no data."""
    timestamp: datetime
    glucose_mgdl: float | None = None
    heart_rate_bpm: float | None = None
    skin_temp_c: float | None = None
    steps: int | None = None
    sleeping: bool | None = None


@dataclass(frozen=True)
class Insight:
    """A plain-language observation for the app to show."""
    timestamp: datetime
    kind: str
    message: str
