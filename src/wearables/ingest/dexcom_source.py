"""Explicit Dexcom G6/G7 data sources for the wearable pipeline."""
from __future__ import annotations

import math
import warnings
from datetime import timezone
from typing import Iterator

from wearables import config
from wearables.ingest.dexcom_backend import DexcomBackend, DexcomError, _parse_time
from wearables.models import Sample

MGDL_PER_MMOLL = 18.016


class DexcomSource:
    """Shared source behavior. Concrete G6/G7 classes select device model explicitly."""
    device_model = "unspecified"
    source_name = "dexcom"
    _GENERATION_MODELS = {"g6": "G6", "g6+": "G6", "g6pro": "G6", "g7": "G7"}
    _VARIANT_MODELS = {"g6": "G6", "g7": "G7", "g715day": "G7"}

    def __init__(self, backend: DexcomBackend, *, history_days: int = 1,
                 use_data_range: bool = False):
        if history_days <= 0:
            raise ValueError("history_days must be positive")
        self.backend = backend
        self.history_days = history_days
        self.use_data_range = use_data_range
        # Kept alongside, not inside, wearables.models.Sample so the public Sample
        # shape remains unchanged while dashboard views retain Dexcom timestamps.
        self.reading_metadata: list[dict] = []

    def samples(self) -> Iterator[Sample]:
        records = self.backend.glucose_records(days=self.history_days,
                                               use_data_range=self.use_data_range)
        normalized = []
        metadata = []
        unverified_identity = False
        for record in records:
            if not isinstance(record, dict):
                continue
            observed_models = self._record_models(record)
            if any(model != self.device_model for model in observed_models):
                found = ", ".join(sorted(observed_models))
                raise DexcomError(f"selected {self.device_model} adapter received metadata for {found}")
            if not observed_models:
                unverified_identity = True
            try:
                timestamp = _parse_time(record.get("systemTime")).replace(tzinfo=None)
                value = record.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    continue
                unit = record.get("unit")
                if unit == "mmol/L":
                    # Assumption: the numeric `value` is expressed in the record's unit.
                    # Dexcom documentation also describes EGV values as mg/dL universally;
                    # validate this behavior against the target sandbox/region before use.
                    value *= MGDL_PER_MMOLL
                elif unit not in (None, "mg/dL"):
                    continue
                sample = Sample(timestamp, config.GLUCOSE, float(value))
                normalized.append((sample, {
                    "timestamp_original": record.get("systemTime"),
                    "timestamp_epoch": timestamp.replace(tzinfo=timezone.utc).timestamp(),
                    "mgdl": float(value),
                    "unit_original": unit,
                    "status": record.get("status"),
                    "trend": record.get("trend"),
                    "trend_rate": record.get("trendRate"),
                }))
            except DexcomError:
                continue
        if unverified_identity:
            warnings.warn(
                f"Dexcom response did not provide recognizable device metadata; "
                f"{self.device_model} was selected explicitly but could not be verified.",
                RuntimeWarning, stacklevel=2)
        normalized.sort(key=lambda pair: pair[0].timestamp)
        self.reading_metadata = [item for _, item in normalized]
        yield from (sample for sample, _ in normalized)

    @classmethod
    def _record_models(cls, record: dict) -> set[str]:
        """Return only model identities supported by recognized Dexcom metadata."""
        result = set()
        generation = record.get("transmitterGeneration")
        if isinstance(generation, str) and generation.lower() in cls._GENERATION_MODELS:
            result.add(cls._GENERATION_MODELS[generation.lower()])
        variant = record.get("transmitterGenerationVariant")
        if isinstance(variant, str) and variant.lower() in cls._VARIANT_MODELS:
            result.add(cls._VARIANT_MODELS[variant.lower()])
        display_app = record.get("displayApp")
        if isinstance(display_app, str) and display_app.strip().lower() in ("g6", "g7"):
            result.add(display_app.strip().upper())
        return result
