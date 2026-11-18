# Wearables mobile app prototype

An installable, responsive PWA dashboard for Android and iOS. The included Python server runs the GitHub `sensor_integration.py` module with simulated samples and exposes a local JSON summary. The app is designed around the awareness-only boundary in the project handoff.

## Run locally

Install Python 3.10+, run `python server.py` from this folder, and open `http://localhost:8000`. For phone installation, host this server on an HTTPS address reachable by the phone, then use **Add to Home Screen** on iOS Safari or **Install app** in Android Chrome. The service worker caches the interface for offline viewing. The Python server must stay running to refresh demo readings.

## Current scope

- Daily glucose trend, heart rate, movement, EDA and sleep overview.
- Glucose display toggle between mg/dL and mmol/L.
- Responsive phone layout, accessible control labels, and offline app shell.
- Simulated sample data only, provided by the repository's Python module. No sensor permissions, real CGM connection, accounts, cloud sync or medical recommendations.

## Dexcom G6/G7 integration

The modular pipeline in `src/wearables` can consume Dexcom through explicit device adapters. Choose the source class that matches the configured account/device. Where Dexcom response metadata clearly identifies a G6 or G7 transmitter, the adapter checks it and raises an error on a mismatch. If metadata is absent or unrecognized, it warns that the explicitly selected model could not be verified; it does not invent device identity.

1. Install dependencies: `python -m pip install -r requirements.txt`.
2. Create a local `.env` (already excluded by `.gitignore`) with `DEXCOM_CLIENT_ID`, `DEXCOM_CLIENT_SECRET`, `DEXCOM_REDIRECT_URI` (for example `http://localhost:8000/callback`) and `DEXCOM_BASE_URL` (the sandbox host, `https://sandbox-api.dexcom.com`). Register the same redirect URI in the Dexcom developer application. Keep this file private.
3. From the repository root, run the interactive sandbox smoke test with `PYTHONPATH=src python dexcom_sandbox_test.py`. It opens OAuth login and prints a small sample of returned readings; it does not print credentials or tokens.

To use the readings in existing processing and analytics, instantiate the shared backend and selected device source, then pass the source to the existing pipeline:

```python
from wearables.ingest.dexcom_backend import DexcomBackend
from wearables.ingest.dexcom_g6 import DexcomG6Source  # or wearables.ingest.dexcom_g7
from wearables.pipeline import run

backend = DexcomBackend.from_env()
backend.login()  # interactive OAuth; the resulting token remains in memory
source = DexcomG6Source(backend, history_days=1)
readings, insights = run(source)  # shared alignment and analytics modules
```

Set `use_data_range=True` for sandbox datasets whose readings are outside the recent time window. G6 and G7 use the same v3 backend and normalized glucose model; the separate adapters make device selection explicit. Readings are normalized to the pipeline's naive UTC `datetime`, `glucose_mgdl` signal, and mg/dL value. The converter assumes each numeric EGV value follows its record's `unit` field: `mmol/L` is multiplied by 18.016, `mg/dL` (or an omitted unit for compatibility) is kept as-is, and an explicit unsupported/unknown unit is skipped. Dexcom's documentation also describes EGV numeric values as mg/dL, so verify actual sandbox responses for the account/region before relying on mmol/L conversion.

Dexcom status/trend and a quality score are not represented by the existing `wearables.models.Sample` contract. The adapter currently skips invalid readings and does not invent a quality value. Recommended future design: preserve status, trend, trend rate, original unit, and any source quality in a separate immutable metadata sidecar keyed by stable sample identity (for example `(source, UTC timestamp)`), while leaving `Sample(timestamp, signal, value)` unchanged. Treat quality as unknown unless Dexcom supplies a meaningful quality field; do not infer it from glucose status or trend. A later aligned-reading metadata layer can then associate this sidecar with buckets without changing existing consumers.

The backend automatically refreshes near-expiry access tokens and retries a 401 at most once. It keeps the current refresh token and expiry in memory for the life of the backend instance; process restart requires a new OAuth login because token persistence is not configured. The legacy top-level `sensor_integration.py` and its SQLite integration remain unchanged.

Run offline tests (mocked API responses; no credentials or network access): `PYTHONPATH=src python -m unittest discover -s tests -v`. Health data should remain local until the project's encryption and sharing requirements are implemented.
