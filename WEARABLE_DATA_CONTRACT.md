# Wearable prototype data contract (draft v1)

This is the software-side starting point for the proposed nRF52840/ISP1807 wearable. It does not assume finalized wiring, sensor configuration, sampling rates, or signal-processing algorithms. It defines what a phone relay can send to the dashboard once the hardware team can produce computed readings.

## Data path

`sensors → ISP1807 firmware → Bluetooth LE → phone relay → HTTPS dashboard API`

The Bluetooth GATT service and characteristics are deliberately not specified yet. The phone relay is also future work. This repository currently implements only the authenticated HTTPS ingestion endpoint and dashboard-side handling.

## Endpoint

`POST /api/device/readings`

Headers:

```text
Content-Type: application/json
Authorization: Bearer <WEARABLE_INGEST_TOKEN>
```

Example payload:

```json
{
  "schema_version": 1,
  "device_id": "prototype-01",
  "readings": [
    {"signal": "heart_rate_bpm", "timestamp": "2026-11-22T14:30:00Z", "value": 72, "unit": "bpm", "quality": 0.92},
    {"signal": "spo2_percent", "timestamp": "2026-11-22T14:30:00Z", "value": 98, "unit": "%"},
    {"signal": "skin_temp_c", "timestamp": "2026-11-22T14:30:00Z", "value": 33.4, "unit": "Cel"},
    {"signal": "steps", "timestamp": "2026-11-22T14:30:00Z", "value": 12, "unit": "count"},
    {"signal": "hrv_ms", "timestamp": "2026-11-22T14:30:00Z", "value": 42, "unit": "ms"}
  ]
}
```

Supported computed values and expected units:

| `signal` | Unit | Dashboard handling |
| --- | --- | --- |
| `heart_rate_bpm` | `bpm` | Saved to history and replaces the demo heart-rate value/chart when available |
| `hrv_ms` | `ms` | Saved in prototype history for future UI |
| `spo2_percent` | `%` | Saved in prototype history for future UI |
| `skin_temp_c` | `Cel` | Saved in prototype history for future UI |
| `steps` | `count` | Count accumulated during the interval ending at the timestamp; saved to movement history |
| `ecg_mv` | `mV` | Individual waveform sample; saved in prototype history, but not charted yet |

Each reading needs an ISO-8601 timestamp with a timezone (UTC is recommended). Batch up to 1,000 readings / 1 MB per request. The server accepts readings from the last 30 days and rejects timestamps more than five minutes in the future. `quality`, when supplied, must be from 0 to 1 and should only represent a firmware-derived signal-quality score. If omitted, the server stores it as “unassessed” at the pipeline's minimum displayable weight; that does not mean the reading is known to be good.

The accepted numeric ranges are format sanity checks only. They are not clinical limits or validation of a sensor. Duplicate `(device, signal, timestamp)` readings are ignored by the SQLite uniqueness rule.

## Not part of this draft

- Glucose: reserved for the separate glucose sensor team / existing Dexcom data path.
- Raw PPG channels, LED drive configuration, or photodiode samples.
- HRV, SpO₂, step-count, or ECG algorithms and claims of accuracy.
- Bluetooth service UUIDs, characteristic UUIDs, BLE security/pairing, exact cadence, or offline synchronization rules.
- A mobile app that scans the ISP1807 and relays readings. The dashboard endpoint is ready for that future component, but it cannot connect to Bluetooth by itself.
- Display cards/charts for HRV, SpO₂, skin temperature, and ECG. Their data can be ingested and retained for the prototype; corresponding visualizations can be added after the team confirms output format and cadence.

## Configure ingestion

Set `WEARABLE_INGEST_TOKEN` to a random secret of at least 32 characters in the server environment. Keep it separate from dashboard login credentials and never bake it into wearable firmware or a public source file. The phone relay must send it in the HTTPS bearer header. Render's HTTPS endpoint is required for sending health data over the internet. For a local server, configure the same variable before starting the app.

The prototype currently stores readings in `wearables_demo.db`. Local data survives server restarts, but a hosted Render service needs a persistent disk mounted for the database file if readings must survive instance replacement or redeployment. Add `WEARABLE_INGEST_TOKEN` and persistent storage in Render only when the team is ready to send real prototype data.

## Example request (PowerShell)

```powershell
$headers = @{ Authorization = "Bearer $env:WEARABLE_INGEST_TOKEN" }
$payload = @{
  schema_version = 1
  device_id = "prototype-01"
  readings = @(
    @{ signal = "heart_rate_bpm"; timestamp = [DateTime]::UtcNow.ToString("o"); value = 72; unit = "bpm" }
  )
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/device/readings" `
  -ContentType "application/json" -Headers $headers -Body $payload
```
