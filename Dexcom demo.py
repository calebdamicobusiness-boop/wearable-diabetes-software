"""End-to-end demo: Dexcom (sandbox) -> pipeline -> dashboard payload. Replaces dexcom_sandbox_test.py.

Run from the repo root:  python dexcom_demo.py
First run opens the Dexcom login; later runs reuse the saved tokens.
"""
import json

from dashboard_payload import dashboard_payload
from dexcom_auth import DexcomAuth
from dexcom_source import DexcomSource
from sensor_integration import IntegrationPipeline, SampleBuffer


def main() -> None:
    auth = DexcomAuth.from_env()
    if not auth.has_tokens():
        print("No saved login. Opening Dexcom sandbox login...")
        auth.login()
    with SampleBuffer("dexcom_demo.db") as buf:               # *.db is git-ignored
        src = DexcomSource(auth.access_token, base_url=auth.base_url, use_data_range=True)
        pipe = IntegrationPipeline(buf)
        pipe.register(src)
        print("new samples:", pipe.poll())
        if src.last_record is None:
            print("No glucose readings returned.")
            return
        for label, now in (("as of the newest reading", src.last_record["t"] + 60),
                           ("as of right now (shows the stale label)", None)):
            w = pipe.latest({"glucose": "cgm"}, now=now)
            print(f"\n--- {label} ---")
            print(json.dumps(dashboard_payload(w, "mg/dL", src.last_record), indent=2))


if __name__ == "__main__":
    main()