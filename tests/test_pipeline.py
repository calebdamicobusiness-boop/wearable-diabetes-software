import unittest
from datetime import datetime

from wearables import config
from wearables.ingest.mock_source import MockSource
from wearables.models import Sample
from wearables.pipeline import run
from wearables.processing.align import align


class PipelineTests(unittest.TestCase):
    def test_align_averages_and_fills_gaps(self):
        t0 = datetime(2026, 1, 1, 0, 0)
        samples = [
            Sample(t0, config.GLUCOSE, 100),
            Sample(t0.replace(minute=2), config.GLUCOSE, 110),
            Sample(t0.replace(minute=10), config.GLUCOSE, 120),
        ]
        out = align(samples)
        self.assertEqual(len(out), 3)            # 0, 5, 10
        self.assertEqual(out[0].glucose_mgdl, 105)
        self.assertIsNone(out[1].glucose_mgdl)   # gap stays None

    def test_full_pipeline_on_mock_data(self):
        readings, insights = run(MockSource(hours=24))
        self.assertEqual(len(readings), 288)
        self.assertGreater(len(insights), 0)


if __name__ == "__main__":
    unittest.main()
