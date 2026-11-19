"""Local development server that exposes the GitHub sensor pipeline as JSON."""
from __future__ import annotations

import json
import argparse
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone

import sensor_integration as si

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from wearables.ingest.dexcom_backend import DexcomBackend, DexcomError
from wearables.ingest.dexcom_g6 import DexcomG6Source
from wearables.ingest.dexcom_g7 import DexcomG7Source
from wearables.pipeline import run as run_wearable_pipeline
from wearables import config as wearable_config
from wearables.analytics.dashboard import generate_dashboard_insights, generate_pattern_entries
from wearables.models import Sample as WearableSample

DB = ROOT / "wearables_demo.db"
start = time.time() - 6 * 3600
buffer = si.SampleBuffer(str(DB))
pipeline = si.IntegrationPipeline(buffer)
pipeline.register(si.SimulatedSource("cgm", 300, 112, 17, 2.5, start, seed=12))
pipeline.register(si.SimulatedSource("hr", 30, 76, 9, 3.0, start, seed=24))
pipeline.register(si.SimulatedEDASource("eda", start_t=start, seed=36))
pipeline.poll()
dexcom_source = None
dexcom_mode = None


class SampleSnapshot:
    """Adapt one fetched batch to the existing pipeline without making another API call."""
    def __init__(self, samples):
        self._samples = samples

    def samples(self):
        return iter(self._samples)


def _summary_analytics(samples, metadata):
    readings, events = run_wearable_pipeline(SampleSnapshot(samples))
    return readings, generate_dashboard_insights(readings, events), generate_pattern_entries(readings, metadata)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/summary":
            self.send_summary()
            return
        super().do_GET()

    def send_summary(self):
        if dexcom_source is not None:
            self.send_dexcom_summary()
            return
        now = time.time()
        window = pipeline.latest({"glucose": "cgm", "hr": "hr", "eda": "eda"}, now)
        payload = {
            "mode": "simulated",
            "as_of": now,
            "glucose_mgdl": window.glucose_last_mgdl,
            "glucose_age_seconds": window.glucose_age_s(),
            "glucose_history": [
                {"t": sample.t, "mgdl": sample.value, "quality": sample.quality}
                for sample in buffer.query("cgm", now - 6 * 3600, now + 1)
            ],
            "heart_rate_bpm": window.features.get("hr_mean"),
            "eda_tonic_us": window.features.get("eda_tonic_mean"),
            "skin_responses_per_minute": window.features.get("scr_per_min"),
            "confidence": window.confidence,
            "status": window.status,
            "description": si.describe(window),
            "disclaimer": si.DISCLAIMER,
        }
        simulated_samples = buffer.query("cgm", now - 7 * 24 * 3600, now + 1)
        wearable_samples = [
            WearableSample(datetime.fromtimestamp(sample.t, timezone.utc).replace(tzinfo=None),
                           wearable_config.GLUCOSE, sample.value)
            for sample in simulated_samples
        ]
        sim_metadata = [
            {"timestamp_original": datetime.fromtimestamp(sample.t, timezone.utc).isoformat().replace("+00:00", "Z"),
             "timestamp_epoch": sample.t, "mgdl": sample.value}
            for sample in simulated_samples
        ]
        _, payload["insights"], payload["patterns"] = _summary_analytics(wearable_samples, sim_metadata)
        body = json.dumps(payload).encode("utf-8")
        self.send_json(200, body)

    def send_dexcom_summary(self):
        now = time.time()
        try:
            samples = list(dexcom_source.samples())
            readings, insights, patterns = _summary_analytics(samples, dexcom_source.reading_metadata)
        except DexcomError as exc:
            self.send_json(502, {
                "mode": dexcom_mode,
                "source_label": f"Dexcom {dexcom_mode.removeprefix('dexcom_').upper()}",
                "error": str(exc),
                "glucose_mgdl": None,
                "glucose_history": [],
                "insights": [],
                "patterns": [],
                "disclaimer": si.DISCLAIMER,
            })
            return

        glucose_readings = [reading for reading in readings if reading.glucose_mgdl is not None]
        latest = glucose_readings[-1] if glucose_readings else None
        records = dexcom_source.reading_metadata
        latest_record = records[-1] if records else None
        latest_t = latest_record["timestamp_epoch"] if latest_record else now
        # The PWA graph spans six hours. Sandbox history may be old, so anchor this
        # window to the newest returned reading instead of wall-clock time.
        cutoff = latest_t - 6 * 3600
        history = [
            {"t": record["timestamp_epoch"], "mgdl": record["mgdl"]}
            for record in records if cutoff <= record["timestamp_epoch"] <= latest_t
        ]
        payload = {
            "mode": dexcom_mode,
            "source_label": f"Dexcom {dexcom_mode.removeprefix('dexcom_').upper()}",
            "as_of": now,
            "chart_end_t": latest_t,
            "glucose_mgdl": latest_record["mgdl"] if latest_record else None,
            "glucose_age_seconds": max(0.0, now - latest_t) if latest else None,
            "glucose_history": history,
            "insights": insights,
            "patterns": patterns,
            "heart_rate_bpm": None,
            "eda_tonic_us": None,
            "status": "ok" if latest else "no_data",
            "disclaimer": si.DISCLAIMER,
        }
        self.send_json(200, payload)

    def send_json(self, status, payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Wearables mobile app demo server.")
    parser.add_argument("port", nargs="?", type=int, default=8000,
                        help="port to serve on (default: 8000)")
    parser.add_argument("--dexcom", choices=("g6", "g7"),
                        help="connect the dashboard to the selected Dexcom adapter instead of simulated glucose")
    args = parser.parse_args()
    if args.dexcom:
        backend = DexcomBackend.from_env()
        print(f"Opening Dexcom sandbox authorization for {args.dexcom.upper()}...")
        backend.login()
        source_class = DexcomG6Source if args.dexcom == "g6" else DexcomG7Source
        dexcom_source = source_class(backend, history_days=7, use_data_range=True)
        dexcom_mode = f"dexcom_{args.dexcom}"
    print(f"Wearables demo running at http://localhost:{args.port}")
    if dexcom_source is None:
        print("This demo uses simulated samples; no real health-device data is connected.")
    else:
        print(f"Dashboard is using the explicit Dexcom {args.dexcom.upper()} adapter.")
    # The dashboard API has no user authentication. Keep real health data bound to
    # this computer; the simulated demo retains its existing LAN-accessible behavior.
    host = "127.0.0.1" if dexcom_source is not None else "0.0.0.0"
    print(f"Binding dashboard to {host} for {'Dexcom data' if dexcom_source else 'simulated demo data'}.")
    ThreadingHTTPServer((host, args.port), Handler).serve_forever()
