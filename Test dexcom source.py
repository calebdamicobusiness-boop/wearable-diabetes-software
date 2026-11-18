import json
import tempfile
import os
import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from dashboard_payload import dashboard_payload, trend_from_slope
from dexcom_source import DexcomError, DexcomSource
from sensor_integration import IntegrationPipeline, Sample, SampleBuffer, SensorSource, fuse_window

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc).timestamp()


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def rec(epoch, value=110, **kw):
    return {"recordId": "x", "systemTime": iso(epoch), "displayTime": iso(epoch - 18000),
            "value": value, "trend": "flat", "status": None, **kw}


class FakeHttp:
    """Queue of (status, body) replies; remembers every request."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers))
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return r


def ok(records, key="records"):
    return 200, json.dumps({key: records})


def source(http, **kw):
    return DexcomSource(lambda: "SECRET-TOKEN", http_get=http, clock=lambda: NOW, **kw)


class ParsingTests(unittest.TestCase):
    def test_v3_records_become_samples(self):
        s = source(FakeHttp(ok([rec(NOW - 300, 100), rec(NOW, 112)])))
        out = list(s.fetch())
        self.assertEqual([(x.t, x.value, x.quality, x.source) for x in out],
                         [(NOW - 300, 100.0, 1.0, "cgm"), (NOW, 112.0, 1.0, "cgm")])

    def test_v2_egvs_key_also_accepted(self):
        self.assertEqual(len(list(source(FakeHttp(ok([rec(NOW)], key="egvs"))).fetch())), 1)

    def test_missing_or_bad_values_skipped_not_invented(self):
        bad = [rec(NOW, None), rec(NOW - 60, "abc"), rec(NOW - 120, True), {"value": 100},
               "junk", rec(NOW - 180, 105)]
        out = list(source(FakeHttp(ok(bad))).fetch())
        self.assertEqual([x.value for x in out], [105.0])

    def test_mmol_converted_to_mgdl(self):
        out = list(source(FakeHttp(ok([rec(NOW, 5.0, unit="mmol/L")]))).fetch())
        self.assertAlmostEqual(out[0].value, 90.08, places=2)

    def test_low_status_kept_and_exposed(self):
        s = source(FakeHttp(ok([rec(NOW, 39, status="low")])))
        self.assertEqual(len(list(s.fetch())), 1)
        self.assertEqual(s.last_record["status"], "low")

    def test_is_a_sensor_source(self):
        self.assertIsInstance(source(FakeHttp(ok([]))), SensorSource)


class RequestTests(unittest.TestCase):
    def test_token_only_in_header_never_in_url(self):
        http = FakeHttp(ok([rec(NOW)]))
        list(source(http).fetch())
        url, headers = http.calls[0]
        self.assertNotIn("SECRET-TOKEN", url)
        self.assertEqual(headers["Authorization"], "Bearer SECRET-TOKEN")

    def test_first_call_backfills_then_incremental(self):
        http = FakeHttp(ok([rec(NOW)]))
        s = source(http, backfill_s=3600)
        list(s.fetch()); list(s.fetch())
        q1 = parse_qs(urlparse(http.calls[0][0]).query)
        q2 = parse_qs(urlparse(http.calls[1][0]).query)
        self.assertEqual(q1["startDate"], [iso(NOW - 3600)])
        self.assertEqual(q2["startDate"], [iso(NOW - 300)])      # last reading minus one period

    def test_data_range_used_for_sandbox(self):
        end = NOW - 86400 * 30
        rng = (200, json.dumps({"egvs": {"end": {"systemTime": iso(end)}}}))
        http = FakeHttp(rng, ok([rec(end)]))
        list(source(http, use_data_range=True, backfill_s=7200).fetch())
        self.assertTrue(urlparse(http.calls[0][0]).path.endswith("/dataRange"))
        self.assertEqual(parse_qs(urlparse(http.calls[1][0]).query)["endDate"], [iso(end)])


class FailureTests(unittest.TestCase):
    def fails(self, reply, text):
        with self.assertRaises(DexcomError) as cm:
            list(source(FakeHttp(reply)).fetch())
        self.assertIn(text, str(cm.exception))
        self.assertNotIn("SECRET-TOKEN", str(cm.exception))

    def test_unauthorized(self):    self.fails((401, ""), "token expired")
    def test_rate_limited(self):    self.fails((429, ""), "rate limited")
    def test_server_error(self):    self.fails((503, ""), "server error")
    def test_unexpected_status(self): self.fails((404, ""), "unexpected")
    def test_not_json(self):        self.fails((200, "<html>"), "not JSON")
    def test_wrong_shape(self):     self.fails((200, "[]"), "unexpected shape")
    def test_no_records_list(self): self.fails((200, "{}"), "no records")
    def test_network_error(self):
        with self.assertRaises(OSError):                      # fake raises directly; real client wraps it
            list(source(FakeHttp(OSError("boom"))).fetch())

    def test_no_token(self):
        s = DexcomSource(lambda: None, http_get=FakeHttp(ok([])))
        with self.assertRaises(DexcomError):
            list(s.fetch())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.addCleanup(self.d.cleanup)
        self.buf = SampleBuffer(os.path.join(self.d.name, "b.db")); self.addCleanup(self.buf.close)

    def test_api_failure_does_not_crash_poll_or_block_other_sources(self):
        class Other(SensorSource):
            def __init__(self): super().__init__("hr", 30)
            def fetch(self): return [Sample(NOW, 70, 1.0, "hr")]
        pipe = IntegrationPipeline(self.buf)
        pipe.register(source(FakeHttp((500, ""))))
        pipe.register(Other())
        added = pipe.poll()
        self.assertEqual(added, {"cgm": 0, "hr": 1})

    def test_repeat_poll_does_not_duplicate(self):                 # backfill overlap is safe (S9)
        pipe = IntegrationPipeline(self.buf)
        pipe.register(source(FakeHttp(ok([rec(NOW - 300), rec(NOW)]))))
        pipe.poll(); pipe.poll()
        self.assertEqual(self.buf.count("cgm"), 2)

    def test_end_to_end_to_dashboard_payload(self):
        recs = [rec(NOW - 300 * i, 111 - i, trend="fortyFiveUp") for i in range(12)][::-1]
        src = source(FakeHttp(ok(recs)))
        pipe = IntegrationPipeline(self.buf); pipe.register(src); pipe.poll()
        w = pipe.latest({"glucose": "cgm"}, now=NOW)
        p = dashboard_payload(w, "mg/dL", src.last_record)
        self.assertEqual((p["glucose"]["state"], p["glucose"]["value"], p["glucose"]["trend"]),
                         ("current", 111, "rising slowly"))
        self.assertEqual(p["range"]["pct_in_range"], 100)
        self.assertIn("awareness", p["note"].lower())
        json.dumps(p)                                              # must be JSON-serialisable

    def test_stale_data_is_labeled_and_has_no_trend(self):         # sandbox / delayed feed
        src = source(FakeHttp(ok([rec(NOW - 3 * 3600)])))
        pipe = IntegrationPipeline(self.buf); pipe.register(src); pipe.poll()
        p = dashboard_payload(pipe.latest({"glucose": "cgm"}, now=NOW), "mg/dL", src.last_record)
        self.assertEqual(p["glucose"]["state"], "stale")
        self.assertEqual(p["glucose"]["age_min"], 180)
        self.assertIsNone(p["glucose"]["trend"])
        self.assertEqual(p["window"]["status"], "suppressed")

    def test_no_data_payload(self):
        w = fuse_window(self.buf, {"glucose": "cgm"}, NOW)
        self.assertEqual(dashboard_payload(w)["glucose"]["state"], "none")

    def test_mmol_display(self):
        src = source(FakeHttp(ok([rec(NOW, 126)])))
        pipe = IntegrationPipeline(self.buf); pipe.register(src); pipe.poll()
        g = dashboard_payload(pipe.latest({"glucose": "cgm"}, now=NOW), "mmol/L")["glucose"]
        self.assertEqual((g["value"], g["unit"]), (7.0, "mmol/L"))

    def test_low_status_shown_as_plain_fact(self):
        src = source(FakeHttp(ok([rec(NOW, 39, status="low")])))
        pipe = IntegrationPipeline(self.buf); pipe.register(src); pipe.poll()
        g = dashboard_payload(pipe.latest({"glucose": "cgm"}, now=NOW), last_record=src.last_record)["glucose"]
        self.assertEqual(g["out_of_sensor_range"], "low")


class TrendTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual([trend_from_slope(x) for x in (0.5, -0.5, 1.5, -2.5, 3.5, -4)],
                         ["steady", "steady", "rising slowly", "falling", "rising quickly", "falling quickly"])


if __name__ == "__main__":
    unittest.main()