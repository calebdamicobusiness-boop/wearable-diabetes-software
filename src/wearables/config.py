"""Central settings. Change values here, not scattered through the code."""

BUCKET_MINUTES = 5  # all signals are aligned to this time grid

# Signal names used everywhere (keeps typos out of the code)
GLUCOSE = "glucose_mgdl"
HEART_RATE = "heart_rate_bpm"
SKIN_TEMP = "skin_temp_c"
STEPS = "steps"
SLEEPING = "sleeping"

# PLACEHOLDER thresholds: confirm with advisors before relying on them.
RAPID_RISE_MGDL_PER_30MIN = 40
RAPID_DROP_MGDL_PER_30MIN = -40
ACTIVE_STEPS_PER_BUCKET = 200

# Heart-rate validation bounds for ingest/hr_source.py. Readings outside are rejected
# (kept in BpmSource.rejected). PLACEHOLDER: confirm with the hardware team / advisors.
HR_MIN_BPM = 30
HR_MAX_BPM = 220

# NEW: freshness. A glucose reading older than this is shown as "stale".
# PLACEHOLDER: depends on the CGM vendor path. Some vendor cloud paths delay
# data by an hour, so confirm with the hardware team / advisors.
STALE_AFTER_MINUTES = 15

# NEW: unit handling (S6). Data is always stored in mg/dL; convert only for display.
MGDL_PER_MMOLL = 18.016
DEFAULT_GLUCOSE_UNIT = "mg/dL"  # or "mmol/L"

# NEW: local buffer (S9). Samples older than this are deleted.
BUFFER_RETENTION_HOURS = 72

DISCLAIMER = (
    "For awareness only. This is not a diagnosis and not advice on "
    "insulin dosing. Talk to a healthcare professional about your health."
)