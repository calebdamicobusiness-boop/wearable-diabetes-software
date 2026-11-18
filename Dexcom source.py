"""Dexcom Developer API (v3) adapter for sensor_integration.py.

Plugs into the existing pipeline as one more SensorSource:

    pipe = IntegrationPipeline(SampleBuffer("health_buffer.db"))
    pipe.register(DexcomSource(token_provider=get_token))   # sandbox by default
    pipe.poll()

Notes
- Uses only the standard library. The HTTP call is injectable (`http_get`) so tests never
  touch the network.
- The OAuth flow is NOT in this file. Pass `token_provider`, a function that returns a
  currently valid access token (refreshing it if needed). Never hard-code tokens.
- The Dexcom API is a retrospective feed: values arrive delayed (documented as hours in some
  setups), and the sandbox serves old canned data. Both show up honestly as "stale" via the
  freshness labels. This is not a real-time source.
- Awareness only (S4): this file reads glucose values; it never interprets them.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from sensor_integration import MGDL_PER_MMOLL, Sample, SensorSource

SANDBOX_URL = "https://sandbox-api.dexcom.com"
PRODUCTION_URL = "https://api.dexcom.com"        # EU: api.dexcom.eu, Japan: api.dexcom.jp
_TS_FMT = "%Y-%m-%dT%H:%M:%S"


class DexcomError(RuntimeError):
    """Any failure talking to Dexcom. Messages never include tokens or response bodies."""


HttpGet = Callable[[str, dict, float], "tuple[int, str]"]


def _urllib_get(url: str, headers: dict, timeout: float) -> "tuple[int, str]":
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:           # 4xx/5xx still carry a status code
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DexcomError(f"network error: {type(e).__name__}") from None


def _to_epoch(ts: Any) -> Optional[float]:
    """ISO-8601 -> UTC epoch seconds. Timestamps without an offset are treated as UTC
    (Dexcom's systemTime is UTC)."""
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class DexcomSource(SensorSource):
    def __init__(
        self,
        token_provider: Callable[[], Optional[str]],
        base_url: str = SANDBOX_URL,
        name: str = "cgm",
        backfill_s: float = 3 * 3600,
        use_data_range: bool = False,
        http_get: Optional[HttpGet] = None,
        timeout_s: float = 10.0,
        clock: Callable[[], float] = time.time,
    ):
        super().__init__(name, expected_period_s=300)     # one reading about every 5 min
        self.token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self.backfill_s = backfill_s
        self.use_data_range = use_data_range              # True for the sandbox: its data is old
        self.http_get = http_get or _urllib_get
        self.timeout_s = timeout_s
        self.clock = clock
        self._last_t: Optional[float] = None
        # Newest record's extra fields (trend, status...). Sample only holds t/value/quality/source.
        self.last_record: Optional[dict] = None

    # ------------------------------------------------------------------ HTTP
    def _get_json(self, path: str, params: Optional[dict] = None) -> dict:
        token = self.token_provider()
        if not token:
            raise DexcomError("no access token available")
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        status, body = self.http_get(url, {"Authorization": f"Bearer {token}"}, self.timeout_s)
        if status == 401 or status == 403:
            raise DexcomError(f"HTTP {status}: token expired, revoked or not authorized")
        if status == 429:
            raise DexcomError("HTTP 429: rate limited, try again later")
        if status >= 500:
            raise DexcomError(f"HTTP {status}: Dexcom server error")
        if status != 200:
            raise DexcomError(f"HTTP {status}: unexpected response")
        try:
            data = json.loads(body)
        except ValueError:
            raise DexcomError("malformed response (not JSON)") from None
        if not isinstance(data, dict):
            raise DexcomError("malformed response (unexpected shape)")
        return data

    # ----------------------------------------------------------------- fetch
    def _window_end(self) -> float:
        if not self.use_data_range:
            return self.clock()
        rng = self._get_json("/v3/users/self/dataRange")
        end = _to_epoch(((rng.get("egvs") or {}).get("end") or {}).get("systemTime"))
        if end is None:
            raise DexcomError("dataRange has no glucose records")
        return end

    def fetch(self) -> Iterable[Sample]:
        end = self._window_end()
        # Small overlap on purpose: the buffer ignores duplicates, so re-reading is harmless.
        start = (self._last_t - self.expected_period_s) if self._last_t else end - self.backfill_s
        data = self._get_json("/v3/users/self/egvs", {
            "startDate": datetime.fromtimestamp(start, timezone.utc).strftime(_TS_FMT),
            "endDate": datetime.fromtimestamp(end, timezone.utc).strftime(_TS_FMT),
        })
        records = data.get("records", data.get("egvs"))     # v3 uses "records"; v2 used "egvs"
        if not isinstance(records, list):
            raise DexcomError("malformed response (no records list)")

        samples, newest = [], None
        for rec in records:
            if not isinstance(rec, dict):
                continue
            t, value = _to_epoch(rec.get("systemTime")), rec.get("value")
            if t is None or isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                continue                                   # missing reading: skip, never invent one
            if rec.get("unit") == "mmol/L":
                value = value * MGDL_PER_MMOLL            # store mg/dL everywhere
            # status "high"/"low" means outside the sensor's range (value is the 400/40 limit).
            # Kept at full quality so the app can show it; the status is exposed in last_record.
            samples.append(Sample(t, float(value), 1.0, self.name))
            if newest is None or t > newest[0]:
                newest = (t, rec)
        if newest:
            self._last_t = max(self._last_t or 0.0, newest[0])
            self.last_record = {"t": newest[0], "trend": newest[1].get("trend"),
                                "trend_rate": newest[1].get("trendRate"),
                                "status": newest[1].get("status")}
        return samples