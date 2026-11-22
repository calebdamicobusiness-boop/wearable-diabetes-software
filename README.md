# Wearables mobile app prototype

An installable, responsive PWA dashboard for Android and iOS. The included Python server runs the GitHub `sensor_integration.py` module with simulated samples and exposes a local JSON summary. The app is designed around the awareness-only boundary in the project handoff.

## Run locally

Install Python 3.10+, copy `.env.example` to `.env`, and choose a private `DASHBOARD_USERNAME` and strong `DASHBOARD_PASSWORD`. Run `python server.py` from this folder and open `http://localhost:8000`; enter those credentials when prompted. For phone installation, host this server on an HTTPS address reachable by the phone, then use **Add to Home Screen** on iOS Safari or **Install app** in Android Chrome. The service worker caches the interface for offline viewing. The Python server must stay running to refresh demo readings.

## Current scope

- Daily glucose trend, heart rate, movement, EDA and sleep overview.
- Expandable signal charts with today, one-week and one-month ranges. Simulated mode seeds up to 30 days of labeled sample history; Dexcom mode charts glucose only and provides at most seven days from its selected sandbox data range.
- Descriptive post-meal glucose comparisons after meal times are logged. Meal timestamps stay in browser storage; the app compares the latest reading in the 30 minutes before a logged meal with the highest available reading in the following two hours.
- Glucose display toggle between mg/dL and mmol/L.
- Responsive phone layout, accessible control labels, and offline app shell.
- Simulated sample data by default, clearly labeled in the dashboard. An opt-in local Dexcom G6/G7 mode is available for sandbox validation. The app does not calculate or recommend insulin doses.
- Draft Bluetooth prototype ingestion contract for computed ISP1807-relayed heart rate, HRV, SpO₂, skin temperature, interval steps, and ECG samples. The server accepts authenticated phone-relay HTTPS batches; Bluetooth pairing and the phone relay are not implemented yet. See [WEARABLE_DATA_CONTRACT.md](WEARABLE_DATA_CONTRACT.md).

## Dexcom G6/G7 integration

The modular pipeline in `src/wearables` can consume Dexcom through explicit device adapters. Choose the source class that matches the configured account/device. Where Dexcom response metadata clearly identifies a G6 or G7 transmitter, the adapter checks it and raises an error on a mismatch. If metadata is absent or unrecognized, it warns that the explicitly selected model could not be verified; it does not invent device identity.

1. Install dependencies: `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` (already excluded by `.gitignore`), set a private `DASHBOARD_USERNAME` and strong `DASHBOARD_PASSWORD`, and keep the file private. The first browser authentication sets an HTTP-only, signed cookie valid for 30 days, so you do not need to re-enter credentials on each visit. Changing the dashboard password invalidates existing cookies.
3. For Dexcom sandbox testing, also set `DEXCOM_CLIENT_ID`, `DEXCOM_CLIENT_SECRET`, `DEXCOM_REDIRECT_URI` (for example `http://localhost:8000/callback`) and `DEXCOM_BASE_URL` (`https://sandbox-api.dexcom.com`). Register the same redirect URI in the Dexcom developer application.
4. From the repository root, run the interactive sandbox smoke test with `PYTHONPATH=src python dexcom_sandbox_test.py`. It opens OAuth login and prints a small sample of returned readings; it does not print credentials or tokens.

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

Run offline tests (mocked API responses; no Dexcom credentials or network access): `PYTHONPATH=src python -m unittest discover -s tests -v`. Health data should remain local until the project's encryption and sharing requirements are implemented.

### Show Dexcom data in the dashboard

From the repository root in PowerShell, with the dashboard credentials and Dexcom sandbox values configured in `.env`, start the dashboard in the selected device mode:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe server.py --dexcom g6
```

For G7, run `.\.venv\Scripts\python.exe server.py --dexcom g7` instead. The server opens the OAuth browser flow before it starts listening; select the corresponding **Sandbox User - G6** or **Sandbox User - G7** account. The configured `DEXCOM_REDIRECT_URI` must match the registered callback and the server port (default `8000`). Then open `http://localhost:8000`.

In Dexcom mode, `/api/summary` reads through the selected device adapter, calls the shared `wearables.pipeline.run()` processing and analytics path, and returns normalized glucose history and generated insights to the PWA. Sandbox history is requested relative to Dexcom's `dataRange` endpoint, so older canned readings can still populate the chart. Connection or model-metadata errors are shown as unavailable; the dashboard does not silently substitute simulated glucose. Dexcom OAuth testing remains local-only: the dashboard binds to `127.0.0.1`, and its OAuth callback accepts localhost redirect URIs only. Other signals are marked not connected.

The dashboard and all API endpoints require authentication in both simulated and Dexcom modes. A signed, HTTP-only cookie remembers a successful browser authentication for 30 days. The server fails closed when `DASHBOARD_USERNAME` or `DASHBOARD_PASSWORD` is missing. Do not expose local Dexcom testing to a LAN; the local-only binding is deliberate. Dexcom tokens are held in process memory, so restart the OAuth flow after restarting the server.

The separate `POST /api/device/readings` prototype endpoint requires a `WEARABLE_INGEST_TOKEN` bearer token (at least 32 characters). This is intended for a future phone relay and is not the dashboard password. It accepts only the draft v1 fields in `WEARABLE_DATA_CONTRACT.md`; it does not accept glucose or raw optical sensor data. Bluetooth connection/firmware and the phone relay are still to be built once the hardware details are agreed. Render's filesystem is ephemeral by default; configure a persistent disk mounted for `wearables_demo.db` before relying on stored device history across restarts or deploys.

### Render configuration

Create a Render **Web Service** connected to this repository and branch. Set the build command to `pip install -r requirements.txt` and the start command to `python server.py`. Add `DASHBOARD_USERNAME` and a long, unique `DASHBOARD_PASSWORD` under the service's Environment settings. Render supplies `PORT`; the server reads it automatically and binds the simulated hosted dashboard to `0.0.0.0`. Do not set `DEXCOM_*` values or start with `--dexcom` on Render: Dexcom's OAuth callback and testing are restricted to localhost. Render provides HTTPS for the hosted service; use the HTTPS URL, and enter the Basic Auth credentials when prompted. These service and environment settings are the remaining manual Render configuration.
