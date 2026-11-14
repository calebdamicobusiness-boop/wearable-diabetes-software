"""
visualize.py - turn buffered sensor data into a clean, shareable report image.

Reads from the SampleBuffer in sensor_integration.py and draws:
  1. Glucose over time (with a configurable reference band, mg/dL or mmol/L)
  2. Heart rate over time
  3. EDA (only if an "eda" source is given), as two panels:
       - Tonic:  the slow baseline skin-conductance level
       - Phasic: the fast skin-conductance responses, with each detected response marked
  4. A data-quality strip showing where insights are ok / low-confidence / suppressed
  5. A footer with summary numbers and the awareness-only note

Design choices tied to the VSD specs:
  S4  every report carries the awareness-only note; no dosing or diagnostic wording
  S5  gaps are drawn as gaps (never interpolated); low-quality samples are faded
  S6  colorblind-safe palette, large text, mg/dL and mmol/L supported
  S8  calm styling, no scores, streaks or red "alarm" colors

Requires: matplotlib  (pip install matplotlib)
"""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # render to file; no GUI needed
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from sensor_integration import (
    AWARENESS_NOTE, BIN_S, MIN_SAMPLE_QUALITY, SampleBuffer, decompose_eda, fuse_window,
)

MGDL_PER_MMOL = 18.016

# Okabe-Ito colorblind-safe palette
C_GLUCOSE = "#0072B2"
C_HR = "#D55E00"
C_EDA = "#CC79A7"
C_PHASIC = "#555555"
C_OK = "#009E73"
C_LOW = "#E69F00"
C_SUPPRESSED = "#BBBBBB"
C_BAND = "#0072B2"
C_TEXT = "#222222"

STATUS_COLORS = {"ok": C_OK, "low_confidence": C_LOW, "suppressed": C_SUPPRESSED}
STATUS_LABELS = {"ok": "Good data", "low_confidence": "Low confidence", "suppressed": "Not enough data"}


def _dt(t: float) -> datetime:
    return datetime.fromtimestamp(t)


def _with_gaps(ts, vs, max_gap_s: float):
    """x/y lists with NaN inserted at gaps so gaps are NOT bridged by a line."""
    xs, ys, prev = [], [], None
    for t, v in zip(ts, vs):
        if prev is not None and t - prev > max_gap_s:
            xs.append(_dt(prev + 1))
            ys.append(float("nan"))
        xs.append(_dt(t))
        ys.append(v)
        prev = t
    return xs, ys


def _line_with_gaps(samples, max_gap_s: float, scale: float = 1.0):
    """Gap-aware line for raw samples, plus faded low-quality points."""
    good = [s for s in samples if s.quality >= MIN_SAMPLE_QUALITY]
    bad = [s for s in samples if s.quality < MIN_SAMPLE_QUALITY]
    xs, ys = _with_gaps([s.t for s in good], [s.value * scale for s in good], max_gap_s)
    return xs, ys, [_dt(s.t) for s in bad], [s.value * scale for s in bad]


def _style_axis(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(labelsize=11, colors=C_TEXT)


def _legend(ax, **kw):
    if ax.get_legend_handles_labels()[0]:         # skip when nothing was drawn
        ax.legend(loc="upper right", frameon=False, fontsize=10, **kw)


def build_report(
    buf: SampleBuffer,
    sources: dict[str, str],
    t_end: Optional[float] = None,
    hours: float = 6,
    out_path: str = "health_report.png",
    glucose_unit: str = "mg/dL",
    ref_range_mgdl: tuple[float, float] = (70, 180),
    title: str = "Wellness overview",
) -> str:
    """sources e.g. {"glucose": "cgm", "hr": "hr", "eda": "eda"}. Returns the saved image path."""
    t_end = t_end or time.time()
    t0 = t_end - hours * 3600
    scale = 1 / MGDL_PER_MMOL if glucose_unit == "mmol/L" else 1.0
    has_eda = "eda" in sources

    g = buf.query(sources["glucose"], t0, t_end) if "glucose" in sources else []
    h = buf.query(sources["hr"], t0, t_end) if "hr" in sources else []
    eda = decompose_eda(buf.query(sources["eda"], t0, t_end)) if has_eda else None

    ratios = [3, 2] + ([1.8, 1.8] if has_eda else []) + [0.7]
    H = 8.5 + (4.0 if has_eda else 0)
    fig, axes = plt.subplots(len(ratios), 1, figsize=(11, H), sharex=True,
                             gridspec_kw={"height_ratios": ratios, "hspace": 0.2})
    ax_g, ax_h, ax_q = axes[0], axes[1], axes[-1]
    fig.suptitle(title, fontsize=18, fontweight="bold", color=C_TEXT, x=0.06, ha="left", y=1 - 0.3 / H)
    fig.text(0.06, 1 - 0.78 / H, f"{_dt(t0):%b %d, %H:%M} to {_dt(t_end):%H:%M}", fontsize=11, color="#555555")

    # --- 1. Glucose ---
    lo, hi = (v * scale for v in ref_range_mgdl)
    ax_g.axhspan(lo, hi, color=C_BAND, alpha=0.08, label=f"Reference band ({lo:.3g}-{hi:.3g})")
    xs, ys, lx, ly = _line_with_gaps(g, max_gap_s=3 * BIN_S, scale=scale)
    if xs:
        ax_g.plot(xs, ys, color=C_GLUCOSE, lw=2.4, marker="o", ms=3.5, label="Glucose")
    if lx:
        ax_g.scatter(lx, ly, marker="x", color=C_GLUCOSE, alpha=0.35, s=24, label="Low-quality reading")
    ax_g.set_ylabel(f"Glucose ({glucose_unit})", fontsize=12, color=C_TEXT)
    _legend(ax_g, ncol=3)
    _style_axis(ax_g)

    # --- 2. Heart rate ---
    xs, ys, lx, ly = _line_with_gaps(h, max_gap_s=2 * BIN_S)
    if xs:
        ax_h.plot(xs, ys, color=C_HR, lw=1.6, label="Heart rate")
    if lx:
        ax_h.scatter(lx, ly, marker="x", color=C_HR, alpha=0.25, s=14, label="Low-quality reading")
    ax_h.set_ylabel("Heart rate (bpm)", fontsize=12, color=C_TEXT)
    _legend(ax_h, ncol=2)
    _style_axis(ax_h)

    # --- 3. EDA: tonic (baseline) and phasic (responses) ---
    if has_eda:
        ax_t, ax_p = axes[2], axes[3]
        xs, ys = _with_gaps(eda.t, eda.tonic, max_gap_s=5.0)
        if xs:
            ax_t.plot(xs, ys, color=C_EDA, lw=2.0, label="Tonic (slow baseline level)")
        ax_t.set_ylabel("Skin conductance\ntonic (µS)", fontsize=12, color=C_TEXT)
        _legend(ax_t)
        _style_axis(ax_t)

        xs, ys = _with_gaps(eda.t, eda.phasic, max_gap_s=5.0)
        if xs:
            ax_p.plot(xs, ys, color=C_PHASIC, lw=0.6, alpha=0.8, label="Phasic (fast responses)")
        if eda.scr_events:
            ax_p.scatter([_dt(t) for t, _ in eda.scr_events], [a for _, a in eda.scr_events],
                         color=C_EDA, s=9, zorder=3, label="Detected response")
        ax_p.axhline(0, color="#999999", lw=0.8)
        ax_p.set_ylabel("Skin conductance\nphasic (µS)", fontsize=12, color=C_TEXT)
        _legend(ax_p, ncol=2)
        _style_axis(ax_p)

    # --- 4. Data-quality strip (S5): one fused window per half hour ---
    step = 1800
    t = math.ceil(t0 / step) * step + step
    counts = {k: 0 for k in STATUS_COLORS}
    while t <= t_end + step:
        w = fuse_window(buf, sources, min(t, t_end))
        ax_q.axvspan(_dt(t - step), _dt(min(t, t_end)), color=STATUS_COLORS[w.status], alpha=0.9)
        counts[w.status] += 1
        t += step
    ax_q.set_yticks([])
    ax_q.set_ylabel("Data\nquality", fontsize=11, color=C_TEXT, rotation=0, labelpad=34, va="center")
    for side in ("top", "right", "left"):
        ax_q.spines[side].set_visible(False)
    ax_q.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_q.tick_params(labelsize=11, colors=C_TEXT)
    ax_q.set_xlim(_dt(t0), _dt(t_end))
    fig.legend(handles=[Patch(color=STATUS_COLORS[k], label=STATUS_LABELS[k]) for k in STATUS_COLORS],
               loc="lower center", bbox_to_anchor=(0.5, 0.85 / H), ncol=3, frameon=False, fontsize=10)

    # --- Summary footer (descriptive only, S4) ---
    parts = []
    gv = [s.value * scale for s in g if s.quality >= MIN_SAMPLE_QUALITY]
    if gv:
        fmt = ".1f" if glucose_unit == "mmol/L" else ".0f"
        parts.append(f"Glucose average {statistics.fmean(gv):{fmt}} {glucose_unit} "
                     f"(range {min(gv):{fmt}} to {max(gv):{fmt}})")
    hv = [s.value for s in h if s.quality >= MIN_SAMPLE_QUALITY]
    if hv:
        parts.append(f"Heart rate average {statistics.fmean(hv):.0f} bpm")
    if eda is not None and eda.t:
        parts.append(f"Skin conductance responses {len(eda.scr_events) / (hours * 60):.1f}/min")
    total = sum(counts.values()) or 1
    parts.append(f"Good data in {counts['ok'] / total:.0%} of the period")
    half = (len(parts) + 1) // 2
    fig.text(0.06, 0.58 / H, "   |   ".join(parts[:half]), fontsize=10.5, color=C_TEXT)
    fig.text(0.06, 0.36 / H, "   |   ".join(parts[half:]), fontsize=10.5, color=C_TEXT)
    fig.text(0.06, 0.12 / H, AWARENESS_NOTE, fontsize=10, color="#666666", style="italic")

    fig.subplots_adjust(left=0.1, right=0.97, top=1 - 1.2 / H, bottom=1.7 / H)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------- #
# Demo: python visualize.py
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from sensor_integration import IntegrationPipeline, SimulatedEDASource, SimulatedSource

    start = time.time() - 6 * 3600
    pipe = IntegrationPipeline()
    pipe.register(SimulatedSource("cgm", 300, 120, 30, 3, start, seed=1))
    pipe.register(SimulatedSource("hr", 30, 75, 12, 4, start, seed=2))
    pipe.register(SimulatedEDASource("eda", start_t=start, seed=3))
    pipe.poll()
    roles = {"glucose": "cgm", "hr": "hr", "eda": "eda"}
    print("saved", build_report(pipe.buffer, roles, hours=6))
    print("saved", build_report(pipe.buffer, roles, hours=6, glucose_unit="mmol/L",
                                out_path="health_report_mmol.png"))
