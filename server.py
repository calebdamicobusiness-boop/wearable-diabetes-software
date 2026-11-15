"""Local development server that exposes the GitHub sensor pipeline as JSON."""
from __future__ import annotations

import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sensor_integration as si

ROOT = Path(__file__).resolve().parent
DB = ROOT / "wearables_demo.db"
start = time.time() - 2 * 3600
buffer = si.SampleBuffer(str(DB))
pipeline = si.IntegrationPipeline(buffer)
pipeline.register(si.SimulatedSource("cgm", 300, 112, 17, 2.5, start, seed=12))
pipeline.register(si.SimulatedSource("hr", 30, 76, 9, 3.0, start, seed=24))
pipeline.register(si.SimulatedEDASource("eda", start_t=start, seed=36))
pipeline.poll()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/summary":
            self.send_summary()
            return
        super().do_GET()

    def send_summary(self):
        now = time.time()
        window = pipeline.latest({"glucose": "cgm", "hr": "hr", "eda": "eda"}, now)
        payload = {
            "mode": "simulated",
            "as_of": now,
            "glucose_mgdl": window.glucose_last_mgdl,
            "glucose_age_seconds": window.glucose_age_s(),
            "heart_rate_bpm": window.features.get("hr_mean"),
            "eda_tonic_us": window.features.get("eda_tonic_mean"),
            "skin_responses_per_minute": window.features.get("scr_per_min"),
            "confidence": window.confidence,
            "status": window.status,
            "description": si.describe(window),
            "awareness_note": si.AWARENESS_NOTE,
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Wearables demo running at http://localhost:8000")
    print("This demo uses simulated samples; no real health-device data is connected.")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
