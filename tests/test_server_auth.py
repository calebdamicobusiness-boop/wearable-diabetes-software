import base64
import os
import threading
import unittest
from http.client import HTTPConnection
from http.server import HTTPServer
from unittest.mock import patch

import server


class DashboardAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), server.Handler)
        cls.httpd.timeout = 3

    @classmethod
    def tearDownClass(cls):
        cls.httpd.server_close()

    def request(self, path, credentials=None, method="GET", cookie=None):
        headers = {}
        if credentials is not None:
            token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        if cookie is not None:
            headers["Cookie"] = cookie
        result = {}

        def send_request():
            connection = HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=3)
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            result["response"] = (response.status, dict(response.getheaders()), response.read())
            connection.close()

        client = threading.Thread(target=send_request)
        client.start()
        self.httpd.handle_request()
        client.join(timeout=3)
        if client.is_alive():
            self.fail("HTTP client did not complete")
        return result["response"]

    @patch.dict(os.environ, {"PORT": "10042"})
    def test_port_uses_render_environment(self):
        self.assertEqual(server.configured_port(), 10042)

    def test_dexcom_and_hosted_bindings(self):
        self.assertEqual(server.server_host(dexcom_enabled=True), "127.0.0.1")
        self.assertEqual(server.server_host(dexcom_enabled=False), "0.0.0.0")

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "tester", "DASHBOARD_PASSWORD": "secret"})
    def test_dashboard_requires_authentication(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 401)
        self.assertIn("Basic", headers["WWW-Authenticate"])
        self.assertEqual(body, b"")

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "tester", "DASHBOARD_PASSWORD": "secret"})
    def test_health_api_requires_authentication(self):
        status, _, _ = self.request("/api/summary")
        self.assertEqual(status, 401)

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "tester", "DASHBOARD_PASSWORD": "secret"})
    def test_valid_credentials_access_dashboard_and_api(self):
        status, headers, body = self.request("/", "tester:secret")
        self.assertEqual(status, 200)
        self.assertIn(b"<!doctype html>", body.lower())
        set_cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Max-Age=2592000", set_cookie)
        cookie = set_cookie.split(";", 1)[0]

        status, headers, body = self.request("/api/summary", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertIn(b'"glucose_mgdl"', body)

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "tester", "DASHBOARD_PASSWORD": "secret"})
    def test_invalid_auth_cookie_is_rejected(self):
        status, _, _ = self.request("/api/summary", cookie="wearables_auth=invalid")
        self.assertEqual(status, 401)

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "tester", "DASHBOARD_PASSWORD": "secret"})
    def test_wrong_credentials_are_rejected(self):
        status, _, _ = self.request("/api/summary", "tester:wrong")
        self.assertEqual(status, 401)

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "", "DASHBOARD_PASSWORD": ""})
    def test_unconfigured_auth_fails_closed(self):
        status, _, _ = self.request("/api/summary")
        self.assertEqual(status, 503)

    @patch.dict(os.environ, {"DASHBOARD_USERNAME": "tester", "DASHBOARD_PASSWORD": "secret"})
    def test_head_request_requires_authentication(self):
        status, _, _ = self.request("/styles.css", method="HEAD")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
