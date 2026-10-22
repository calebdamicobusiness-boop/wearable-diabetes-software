"""Every data source (mock, CGM API, Bluetooth, HealthKit...) follows this."""
from typing import Iterator, Protocol

from wearables.models import Sample


class DataSource(Protocol):
    def samples(self) -> Iterator[Sample]:
        """Yield raw Sample objects."""
        ...
