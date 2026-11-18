"""Interactive smoke test for Dexcom sandbox OAuth and glucose retrieval.

Credentials are read from .env. This script never prints credentials or tokens.
For deterministic/offline tests, see tests/test_dexcom.py.
"""
from wearables.ingest.dexcom_backend import DexcomBackend


def main() -> None:
    backend = DexcomBackend.from_env()
    print("Opening Dexcom login...")
    backend.login()
    records = backend.glucose_records(days=30)
    print("Dexcom API connection successful!")
    print("Number of glucose records:", len(records))
    for record in records[-5:]:
        print("Time:", record.get("systemTime"), "| Glucose:",
              record.get("value"), record.get("unit"), "| Trend:", record.get("trend"))
    if not records:
        print("No readings found in this date window.")


if __name__ == "__main__":
    main()
