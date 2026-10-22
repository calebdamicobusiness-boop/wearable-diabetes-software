"""TODO: wearable data from the hardware team (Bluetooth, file, or phone health app)."""
from typing import Iterator

from wearables.models import Sample


class WearableSource:
    def samples(self) -> Iterator[Sample]:
        raise NotImplementedError("Hook up the hardware team's data here.")
