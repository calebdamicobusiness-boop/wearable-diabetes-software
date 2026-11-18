import unittest
import warnings
from datetime import datetime, timezone

import requests

from wearables.ingest.dexcom_backend import DexcomBackend, DexcomError
from wearables.ingest.dexcom_g6 import DexcomG6Source
from wearables.ingest.dexcom_g7 import DexcomG7Source
from wearables.pipeline import run


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, gets=(), posts=()):
        self.gets, self.posts = list(gets), list(posts)
        self.get_calls, self.post_calls = [], []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        response = self.gets.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        response = self.posts.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def record(minute, value, **extra):
    return {"systemTime": f"2026-01-01T00:{minute:02d}:00Z", "value": value,
            "unit": "mg/dL", "trend": "flat", **extra}


def backend(session):
    return DexcomBackend(client_id="id", client_secret="secret", redirect_uri="http://localhost:8000/callback",
                         base_url="https://sandbox-api.dexcom.com", access_token="test-token", session=session)


class DexcomAdapterTests(unittest.TestCase):
    def test_g6_and_g7_are_explicit_and_normalize_same_model(self):
        for cls, model, signal in ((DexcomG6Source, "G6", "dexcom_g6"),
                                   (DexcomG7Source, "G7", "dexcom_g7")):
            gen = model.lower()
            payload = {"records": [record(10, 110, transmitterGeneration=gen),
                                   record(5, 5.5, unit="mmol/L", transmitterGeneration=gen),
                                   record(15, None, transmitterGeneration=gen),
                                   {"value": 100, "transmitterGeneration": gen}]}
            src = cls(backend(FakeSession(gets=[FakeResponse(200, payload)])))
            self.assertEqual(src.device_model, model)
            samples = list(src.samples())
            self.assertEqual([s.signal for s in samples], ["glucose_mgdl", "glucose_mgdl"])
            self.assertEqual([s.value for s in samples], [5.5 * 18.016, 110])
            self.assertEqual(samples[0].timestamp, datetime(2026, 1, 1, 0, 5))
            self.assertEqual(src.source_name, signal)

    def test_adapter_runs_through_existing_alignment_and_analytics(self):
        rows = []
        for i in range(8):
            minute = i * 5
            rows.append({"systemTime": datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc).isoformat(),
                         "value": 100 + i * 10, "unit": "mg/dL", "transmitterGeneration": "g6"})
        readings, insights = run(DexcomG6Source(backend(FakeSession(
            gets=[FakeResponse(200, {"records": rows})]))))
        self.assertEqual(len(readings), 8)
        self.assertEqual(readings[-1].glucose_mgdl, 170)
        self.assertGreater(len(insights), 0)

    def test_token_is_not_in_request_url_and_api_errors_are_sanitized(self):
        session = FakeSession(gets=[FakeResponse(401, {"message": "secret body"})])
        src = DexcomG7Source(backend(session))
        with self.assertRaises(DexcomError) as caught:
            list(src.samples())
        url, kwargs = session.get_calls[0]
        self.assertNotIn("test-token", url)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertNotIn("secret body", str(caught.exception))
        self.assertNotIn("test-token", str(caught.exception))

    def test_oauth_exchange_uses_form_and_does_not_log_token(self):
        session = FakeSession(posts=[FakeResponse(200, {"access_token": "private-token"})])
        api = DexcomBackend(client_id="id", client_secret="private-secret",
                            redirect_uri="http://localhost:8000/callback",
                            base_url="https://sandbox-api.dexcom.com", session=session)
        self.assertEqual(api.exchange_code("authorization-code"), "private-token")
        _, kwargs = session.post_calls[0]
        self.assertEqual(kwargs["data"]["grant_type"], "authorization_code")
        self.assertEqual(kwargs["data"]["code"], "authorization-code")

    def test_accepts_legacy_egvs_response_key(self):
        src = DexcomG6Source(backend(FakeSession(gets=[FakeResponse(200, {"egvs": [record(1, 100)]})])))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            self.assertEqual(len(list(src.samples())), 1)

    def test_empty_egv_records_return_empty_samples(self):
        src = DexcomG7Source(backend(FakeSession(gets=[FakeResponse(200, {"records": []})])))
        self.assertEqual(list(src.samples()), [])

    def test_malformed_top_level_payloads_are_rejected(self):
        for payload, message in (([], "unexpected shape"), ({}, "no records list"),
                                 ({"records": {}}, "no records list"),
                                 (ValueError("bad json"), "not JSON")):
            with self.subTest(payload=payload):
                src = DexcomG6Source(backend(FakeSession(gets=[FakeResponse(200, payload)])))
                with self.assertRaisesRegex(DexcomError, message):
                    list(src.samples())

    def test_network_failure_is_sanitized(self):
        session = FakeSession(gets=[requests.ConnectionError("private endpoint details")])
        src = DexcomG6Source(backend(session))
        with self.assertRaises(DexcomError) as caught:
            list(src.samples())
        self.assertIn("network error", str(caught.exception))
        self.assertNotIn("private endpoint details", str(caught.exception))

    def test_rate_limit_and_server_errors(self):
        for status, text in ((429, "rate limited"), (500, "server error")):
            with self.subTest(status=status):
                src = DexcomG6Source(backend(FakeSession(gets=[FakeResponse(status, {})])))
                with self.assertRaisesRegex(DexcomError, text):
                    list(src.samples())

    def test_token_endpoint_failure_is_sanitized(self):
        api = DexcomBackend(client_id="id", client_secret="private-secret",
                            redirect_uri="http://localhost:8000/callback",
                            base_url="https://sandbox-api.dexcom.com",
                            session=FakeSession(posts=[FakeResponse(500, {"body": "private"})]))
        with self.assertRaisesRegex(DexcomError, "token request failed") as caught:
            api.exchange_code("authorization-code")
        self.assertNotIn("private-secret", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))

    def test_401_refreshes_once_and_retains_rotated_token_and_expiry(self):
        session = FakeSession(
            gets=[FakeResponse(401, {}), FakeResponse(200, {"records": []})],
            posts=[FakeResponse(200, {"access_token": "rotated-access", "refresh_token": "rotated-refresh",
                                     "expires_in": 7200, "refresh_expires_in": 86400})],
        )
        api = DexcomBackend(client_id="id", client_secret="secret", redirect_uri="http://localhost:8000/callback",
                            base_url="https://sandbox-api.dexcom.com", access_token="old-access",
                            refresh_token="old-refresh", session=session)
        self.assertEqual(api.get_json("/v3/users/self/egvs"), {"records": []})
        self.assertEqual(len(session.get_calls), 2)
        self.assertEqual(session.get_calls[0][1]["headers"]["Authorization"], "Bearer old-access")
        self.assertEqual(session.get_calls[1][1]["headers"]["Authorization"], "Bearer rotated-access")
        self.assertEqual(api.refresh_token_value, "rotated-refresh")
        self.assertGreater(api.token_expires_at, 0)
        self.assertGreater(api.refresh_token_expires_at, 0)

    def test_repeated_401_does_not_loop_or_refresh_twice(self):
        session = FakeSession(gets=[FakeResponse(401, {}), FakeResponse(401, {})],
                              posts=[FakeResponse(200, {"access_token": "new", "refresh_token": "new-r",
                                                       "expires_in": 7200})])
        api = DexcomBackend(client_id="id", client_secret="secret", redirect_uri="http://localhost:8000/callback",
                            base_url="https://sandbox-api.dexcom.com", access_token="old",
                            refresh_token="old-r", session=session)
        with self.assertRaisesRegex(DexcomError, "after token refresh"):
            api.get_json("/v3/users/self/egvs")
        self.assertEqual(len(session.get_calls), 2)
        self.assertEqual(len(session.post_calls), 1)

    def test_proactive_refresh_uses_rotated_refresh_token(self):
        session = FakeSession(gets=[FakeResponse(200, {"records": []})],
                              posts=[FakeResponse(200, {"access_token": "new", "refresh_token": "new-r",
                                                       "expires_in": 3600})])
        api = DexcomBackend(client_id="id", client_secret="secret", redirect_uri="http://localhost:8000/callback",
                            base_url="https://sandbox-api.dexcom.com", access_token="old",
                            refresh_token="old-r", expires_at=1, session=session)
        api.get_json("/v3/users/self/egvs")
        self.assertEqual(api.refresh_token_value, "new-r")
        self.assertEqual(session.get_calls[0][1]["headers"]["Authorization"], "Bearer new")

    def test_metadata_mismatch_raises_clear_error(self):
        payload = {"records": [record(1, 100, transmitterGeneration="g7")]}
        src = DexcomG6Source(backend(FakeSession(gets=[FakeResponse(200, payload)])))
        with self.assertRaisesRegex(DexcomError, "selected G6 adapter received metadata for G7"):
            list(src.samples())

    def test_unavailable_metadata_warns_and_does_not_infer_identity(self):
        payload = {"records": [record(1, 100)]}
        src = DexcomG7Source(backend(FakeSession(gets=[FakeResponse(200, payload)])))
        with self.assertWarnsRegex(RuntimeWarning, "could not be verified"):
            self.assertEqual(len(list(src.samples())), 1)

    def test_g7_adapter_runs_end_to_end_through_pipeline(self):
        rows = []
        for i in range(8):
            timestamp = datetime(2026, 1, 1, 0, i * 5, tzinfo=timezone.utc).isoformat()
            rows.append({"systemTime": timestamp, "value": 100 + i * 10, "unit": "mg/dL",
                         "transmitterGeneration": "g7"})
        readings, insights = run(DexcomG7Source(backend(FakeSession(
            gets=[FakeResponse(200, {"records": rows})]))))
        self.assertEqual(len(readings), 8)
        self.assertEqual(readings[-1].glucose_mgdl, 170)
        self.assertTrue(insights)

    def test_untrusted_or_non_https_base_urls_are_rejected(self):
        for url in ("http://sandbox-api.dexcom.com", "https://attacker.example",
                    "https://sandbox-api.dexcom.com:8443", "https://user@sandbox-api.dexcom.com"):
            with self.subTest(url=url), self.assertRaisesRegex(DexcomError, "trusted Dexcom host"):
                DexcomBackend(client_id="id", client_secret="secret", redirect_uri="http://localhost/cb",
                              base_url=url)


if __name__ == "__main__":
    unittest.main()
