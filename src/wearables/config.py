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

DISCLAIMER = (
    "For awareness only. This is not a diagnosis and not advice on "
    "insulin dosing. Talk to a healthcare professional about your health."
)
