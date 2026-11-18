"""Dexcom G6 device-specific pipeline adapter."""
from wearables.ingest.dexcom_source import DexcomSource


class DexcomG6Source(DexcomSource):
    """Explicit G6 selection; the API response is not used to infer the device model."""
    device_model = "G6"
    source_name = "dexcom_g6"
