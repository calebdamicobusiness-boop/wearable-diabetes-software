"""Dexcom G7 device-specific pipeline adapter."""
from wearables.ingest.dexcom_source import DexcomSource


class DexcomG7Source(DexcomSource):
    """Explicit G7 selection; the API response is not used to infer the device model."""
    device_model = "G7"
    source_name = "dexcom_g7"
