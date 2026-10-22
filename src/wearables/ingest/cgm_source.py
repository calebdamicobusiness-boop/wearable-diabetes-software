"""TODO: real CGM data (e.g., a manufacturer API). Ask advisors what we get."""
from typing import Iterator

from wearables.models import Sample


class CgmSource:
    def samples(self) -> Iterator[Sample]:
        raise NotImplementedError("Hook up the real CGM data here.")
