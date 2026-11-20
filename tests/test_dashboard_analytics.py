import unittest
from datetime import datetime, timedelta

from wearables.analytics.dashboard import generate_dashboard_insights, generate_pattern_entries
from wearables.analytics.insights import generate_insights
from wearables import config
from wearables.models import Reading, Sample
from wearables.pipeline import run


class BatchSource:
    def __init__(self, samples):
        self._samples = samples

    def samples(self):
        return iter(self._samples)


class DashboardAnalyticsTests(unittest.TestCase):
    def test_long_window_insights_require_and_use_observed_data(self):
        start = datetime(2026, 10, 1)
        samples = []
        for day in range(3):
            for slot in range(288):
                timestamp = start + timedelta(days=day, minutes=slot * 5)
                value = 100 + day * 10
                if timestamp.hour == 8 and timestamp.minute < 15:
                    value = 190 + day
                samples.append(Sample(timestamp, config.GLUCOSE, value))

        readings, events = run(BatchSource(samples))
        insights = generate_dashboard_insights(readings, events)
        categories = {item["category"] for item in insights}
        self.assertTrue({"time_in_range", "variability", "daily_comparison", "recurring"} <= categories)
        self.assertTrue(all(item["sample_count"] > 0 for item in insights if "sample_count" in item))
        recurring = next(item for item in insights if item["category"] == "recurring")
        self.assertIn("3 dates", recurring["message"])

    def test_long_window_summaries_are_omitted_without_enough_readings(self):
        readings = [Reading(datetime(2026, 10, 1, 10, 0), glucose_mgdl=120)]
        insights = generate_dashboard_insights(readings)
        self.assertEqual([item["category"] for item in insights], [])

    def test_pattern_entries_group_states_and_keep_original_source_timestamps(self):
        start = datetime(2026, 10, 1, 8, 0)
        values = [100, 101, 190, 60, 100, 99]
        readings = [Reading(start + timedelta(minutes=5 * i), glucose_mgdl=value)
                    for i, value in enumerate(values)]
        original = [
            "2026-10-01T08:00:02.125Z", "2026-10-01T08:05:02.250Z",
            "2026-10-01T08:10:02.375Z", "2026-10-01T08:15:02.500Z",
            "2026-10-01T08:20:02.625Z", "2026-10-01T08:25:02.750Z",
        ]
        records = [
            {"timestamp_original": timestamp,
             "timestamp_epoch": (start + timedelta(minutes=5 * i, seconds=2)).timestamp(),
             "mgdl": value,
             "trend": "fortyFiveDown" if i == 4 else "flat"}
            for i, (timestamp, value) in enumerate(zip(original, values))
        ]
        patterns = generate_pattern_entries(readings, records)
        statuses = {item["status"] for item in patterns}
        self.assertTrue({"High", "Low", "Stable", "Falling"} <= statuses)
        self.assertEqual(patterns, sorted(patterns, key=lambda item: item["timestamp"], reverse=True))
        falling = next(item for item in patterns if item["status"] == "Falling")
        self.assertEqual(falling["timestamp_original"], original[4])

    def test_pattern_entries_empty_when_no_samples(self):
        self.assertEqual(generate_pattern_entries([], []), [])


if __name__ == "__main__":
    unittest.main()
