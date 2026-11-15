# Wearables mobile app prototype

An installable, responsive PWA dashboard for Android and iOS. The included Python server runs the GitHub `sensor_integration.py` module with simulated samples and exposes a local JSON summary. The app is designed around the awareness-only boundary in the project handoff.

## Run locally

Install Python 3.10+, run `python server.py` from this folder, and open `http://localhost:8000`. For phone installation, host this server on an HTTPS address reachable by the phone, then use **Add to Home Screen** on iOS Safari or **Install app** in Android Chrome. The service worker caches the interface for offline viewing. The Python server must stay running to refresh demo readings.

## Current scope

- Daily glucose trend, heart rate, movement, EDA and sleep overview.
- Glucose display toggle between mg/dL and mmol/L.
- Responsive phone layout, accessible control labels, and offline app shell.
- Simulated sample data only, provided by the repository's Python module. No sensor permissions, real CGM connection, accounts, cloud sync or medical recommendations.

## Integration path

The repository's `sensor_integration.py` supplies the Python pipeline and fusion model. The included `server.py` wraps its simulated streams in a small JSON API at `/api/summary`; `app.js` consumes that response. The GitHub module does not yet have live CGM or EDA adapters. A next integration step is to add timestamped sensor adapters and history endpoints once the CGM and wearable hardware are chosen. Health data should remain local until the project's encryption and sharing requirements are implemented.
