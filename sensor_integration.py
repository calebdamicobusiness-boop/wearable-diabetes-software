"""
sensor_integration.py - plug-in framework for CGM + heart-rate (+ future) sensors.

Maps to the VSD specs:
  S1  no third-party sharing -> everything stays in a local SQLite buffer
  S4  awareness-only         -> insights are descriptive, never dosing/diagnosis
  S5  +/-1 min alignment; >10% missing or poor quality -> low-confidence/suppressed
  S9  buffer >=24 h offline, zero lost samples (UNIQUE(source,t) dedupes on re-sync)
  S10 subgroup error report, flag subgroup error > overall * 1.2

Stdlib only (Python 3.10+). To add a sensor: subclass SensorSource, implement
fetch(), register it with the pipeline. Nothing else changes.
"""
from __future__ import annotations

import math
import random
import sqlite3
import statistics
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Optional

AWARENESS_NOTE = "For awareness only. Not medical advice; do not use for insulin dosing."

# Tunable starting values (confirm with advisors)
BIN_S = 300                 # 5-min common time base
WINDOW_BINS = 12            # 1-hour insight window (1 missing bin = 8.3% < 10%)
MAX_MISSING_FRAC = 0.10     # S5: above this -> low confidence
SUPPRESS_MISSING_FRAC = 0.50
MIN_SAMPLE_QUALITY = 0.5    # samples below this count as missing
MIN_WINDOW_QUALITY = 0.6


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Sample:
    t: float            # UTC epoch seconds
    value: float
    quality: float      # 0..1 signal-quality index (use 1.0 if the sensor has none)
    source: str         # e.g. "cgm", "hr"


# --------------------------------------------------------------------------- #
# Sensor adapters
# --------------------------------------------------------------------------- #
class SensorSource(ABC):
    """Base class. Implement fetch() to return NEW samples since the last call."""

    def __init__(self, name: str, expected_period_s: float, clock_offset_s: float = 0.0):
        self.name = name
        self.expected_period_s = expected_period_s   # nominal sample spacing
        self.clock_offset_s = clock_offset_s         # correct known device clock skew (S5)

    @abstractmethod
    def fetch(self) -> Iterable[Sample]:
        ...


class SimulatedSource(SensorSource):
    """Stand-in for development before hardware exists."""

    def __init__(self, name, period_s, base, amp, noise, start_t, dropout=0.05, seed=0):
        super().__init__(name, period_s)
        self._rng = random.Random(seed)
        self._p, self._base, self._amp, self._noise = period_s, base, amp, noise
        self._next_t, self._dropout = start_t, dropout

    def fetch(self):
        now, out = time.time(), []
        while self._next_t <= now:
            t = self._next_t
            self._next_t += self._p
            if self._rng.random() < self._dropout:
                continue
            v = self._base + self._amp * math.sin(t / 2400) + self._rng.gauss(0, self._noise)
            q = self._rng.choice([1.0, 1.0, 0.9, 0.3])   # occasional poor signal
            out.append(Sample(t, v, q, self.name))
        return out


class CSVReplaySource(SensorSource):
    """Replay a recorded/public dataset. CSV columns: t,value[,quality]."""

    def __init__(self, name, expected_period_s, path):
        super().__init__(name, expected_period_s)
        import csv
        with open(path, newline="") as f:
            self._rows = [
                Sample(float(r["t"]), float(r["value"]), float(r.get("quality") or 1.0), name)
                for r in csv.DictReader(f)
            ]
        self._i = 0

    def fetch(self):
        out, self._i = self._rows[self._i:], len(self._rows)
        return out


# Hardware adapters: fill in once the devices/APIs are chosen.
class CGMSource(SensorSource):
    def __init__(self, client, **kw):
        super().__init__("cgm", expected_period_s=300, **kw)
        self.client = client            # vendor SDK / API client

    def fetch(self):
        # TODO: raw = self.client.get_readings(since=...)
        # return [Sample(r.epoch, r.mgdl, 1.0, self.name) for r in raw]
        raise NotImplementedError


class HeartRateSource(SensorSource):
    def __init__(self, device, **kw):
        super().__init__("hr", expected_period_s=30, **kw)
        self.device = device            # BLE handle / wearable SDK

    def fetch(self):
        # TODO: map BPM + signal-quality index from the wearable
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Local buffer (S9, S1)
# --------------------------------------------------------------------------- #
class SampleBuffer:
    def __init__(self, path=":memory:", retention_s=72 * 3600):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS samples("
            "source TEXT, t REAL, value REAL, quality REAL, UNIQUE(source, t))"
        )
        self.retention_s = retention_s

    def add(self, samples: Iterable[Sample]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO samples VALUES (?,?,?,?)",
                [(s.source, s.t, s.value, s.quality) for s in samples],
            )

    def query(self, source: str, t0: float, t1: float) -> list[Sample]:
        rows = self.db.execute(
            "SELECT t,value,quality FROM samples WHERE source=? AND t>=? AND t<? ORDER BY t",
            (source, t0, t1),
        )
        return [Sample(t, v, q, source) for t, v, q in rows]

    def count(self, source: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM samples WHERE source=?", (source,)).fetchone()[0]

    def purge_old(self, now: float) -> None:
        with self.db:
            self.db.execute("DELETE FROM samples WHERE t < ?", (now - self.retention_s,))


# --------------------------------------------------------------------------- #
# Alignment + fusion
# --------------------------------------------------------------------------- #
@dataclass
class BinValue:
    value: Optional[float]      # median of good samples, None if missing
    quality: float              # mean quality of good samples


def bin_signal(samples: list[Sample], t0: float, n_bins: int, bin_s: float = BIN_S) -> list[BinValue]:
    buckets: list[list[Sample]] = [[] for _ in range(n_bins)]
    for s in samples:
        i = int((s.t - t0) // bin_s)
        if 0 <= i < n_bins and s.quality >= MIN_SAMPLE_QUALITY:
            buckets[i].append(s)
    return [
        BinValue(statistics.median(x.value for x in b), statistics.fmean(x.quality for x in b))
        if b else BinValue(None, 0.0)
        for b in buckets
    ]


@dataclass
class FusedWindow:
    t_start: float
    t_end: float
    status: str                         # "ok" | "low_confidence" | "suppressed"
    missing_frac: float
    confidence: float
    features: dict = field(default_factory=dict)
    note: str = AWARENESS_NOTE


def _slope_per_min(ys: list[tuple[int, float]], bin_s: float) -> float:
    xs = [i * bin_s / 60 for i, _ in ys]
    vs = [v for _, v in ys]
    return statistics.linear_regression(xs, vs).slope


def fuse_window(buf: SampleBuffer, sources: dict[str, str], t_end: float,
                n_bins: int = WINDOW_BINS, bin_s: float = BIN_S) -> FusedWindow:
    """sources maps role -> source name, e.g. {"glucose": "cgm", "hr": "hr"}."""
    t_end = math.floor(t_end / bin_s) * bin_s
    t0 = t_end - n_bins * bin_s
    binned = {role: bin_signal(buf.query(name, t0, t_end), t0, n_bins, bin_s)
              for role, name in sources.items()}

    # A bin is usable only if EVERY source has a good value (fused features need all inputs)
    ok_idx = [i for i in range(n_bins) if all(binned[r][i].value is not None for r in binned)]
    missing = 1 - len(ok_idx) / n_bins
    conf = min(                                   # inherit the worst input quality
        (statistics.fmean(binned[r][i].quality for i in ok_idx) for r in binned),
        default=0.0,
    )

    if missing > SUPPRESS_MISSING_FRAC or not ok_idx:
        return FusedWindow(t0, t_end, "suppressed", missing, conf)
    status = "ok" if (missing <= MAX_MISSING_FRAC and conf >= MIN_WINDOW_QUALITY) else "low_confidence"

    feats: dict = {}
    if "glucose" in binned:
        g = [(i, binned["glucose"][i].value) for i in ok_idx]
        feats["glucose_mean"] = statistics.fmean(v for _, v in g)
        if len(g) >= 3:
            feats["glucose_slope_per_min"] = _slope_per_min(g, bin_s)
    if "hr" in binned:
        feats["hr_mean"] = statistics.fmean(binned["hr"][i].value for i in ok_idx)
    if {"glucose", "hr"} <= binned.keys() and len(ok_idx) >= 4:
        gv = [binned["glucose"][i].value for i in ok_idx]
        hv = [binned["hr"][i].value for i in ok_idx]
        try:
            feats["hr_glucose_corr"] = statistics.correlation(gv, hv)
        except statistics.StatisticsError:      # constant input
            feats["hr_glucose_corr"] = None
    return FusedWindow(t0, t_end, status, missing, conf, feats)


def describe(w: FusedWindow) -> str:
    """Descriptive, awareness-only text (S4). Extend with rule-based insights."""
    if w.status == "suppressed":
        return f"Not enough good data in this window to show an insight. {w.note}"
    f, tag = w.features, ("" if w.status == "ok" else " (low confidence)")
    parts = []
    if "glucose_slope_per_min" in f:
        s = f["glucose_slope_per_min"]
        parts.append("glucose rising" if s > 0.5 else "glucose falling" if s < -0.5 else "glucose steady")
    if "hr_mean" in f:
        parts.append(f"average heart rate {f['hr_mean']:.0f} bpm")
    return ("; ".join(parts) or "no features") + tag + ". " + w.note


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class IntegrationPipeline:
    def __init__(self, buffer: Optional[SampleBuffer] = None):
        self.buffer = buffer or SampleBuffer()
        self.sources: list[SensorSource] = []

    def register(self, src: SensorSource) -> None:
        self.sources.append(src)

    def poll(self) -> dict[str, int]:
        """Pull new samples from every source. A failing sensor never blocks the others."""
        added = {}
        for src in self.sources:
            try:
                new = [Sample(s.t + src.clock_offset_s, s.value, s.quality, src.name)
                       for s in src.fetch()]
                self.buffer.add(new)
                added[src.name] = len(new)
            except NotImplementedError:
                raise
            except Exception as e:               # BLE drop, API error, etc.
                added[src.name] = 0
                print(f"[warn] {src.name} fetch failed: {e}")
        self.buffer.purge_old(time.time())
        return added

    def latest(self, roles: dict[str, str], now: Optional[float] = None) -> FusedWindow:
        return fuse_window(self.buffer, roles, now or time.time())


# --------------------------------------------------------------------------- #
# S10 subgroup evaluation
# --------------------------------------------------------------------------- #
def subgroup_error_report(records: list[dict], flag_ratio: float = 1.2) -> dict:
    """records: [{"group": "skin_tone_V", "error": 4.2}, ...] (abs error vs. reference).
    Flags any subgroup whose mean error exceeds overall mean error by > (flag_ratio-1)."""
    overall = statistics.fmean(r["error"] for r in records)
    groups: dict[str, list[float]] = {}
    for r in records:
        groups.setdefault(r["group"], []).append(r["error"])
    return {
        g: {"n": len(v), "mean_error": statistics.fmean(v),
            "flagged": statistics.fmean(v) > overall * flag_ratio}
        for g, v in groups.items()
    } | {"_overall": {"mean_error": overall}}


# --------------------------------------------------------------------------- #
# Demo: python sensor_integration.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    start = time.time() - 2 * 3600                       # pretend 2 h already recorded
    pipe = IntegrationPipeline()
    pipe.register(SimulatedSource("cgm", 300, 120, 30, 3, start, seed=1))
    pipe.register(SimulatedSource("hr", 30, 75, 12, 4, start, seed=2))
    print("added:", pipe.poll())
    w = pipe.latest({"glucose": "cgm", "hr": "hr"})
    print(f"status={w.status} missing={w.missing_frac:.0%} confidence={w.confidence:.2f}")
    print({k: (round(v, 2) if v is not None else None) for k, v in w.features.items()})
    print(describe(w))
    print(subgroup_error_report([
        {"group": "A", "error": 4.0}, {"group": "A", "error": 5.0},
        {"group": "B", "error": 8.0}, {"group": "B", "error": 7.0},
    ]))
