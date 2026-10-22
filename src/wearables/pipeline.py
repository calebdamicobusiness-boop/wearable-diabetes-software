"""Glue: source -> align -> insights. Swap the source and nothing else changes."""
from wearables.analytics.insights import generate_insights
from wearables.ingest.base import DataSource
from wearables.models import Insight, Reading
from wearables.processing.align import align


def run(source: DataSource) -> tuple[list[Reading], list[Insight]]:
    readings = align(source.samples())
    return readings, generate_insights(readings)
