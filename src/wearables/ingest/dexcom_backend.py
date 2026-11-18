"""Shared Dexcom v3 OAuth and API backend.

Device selection belongs to the caller: the API response does not reliably identify
whether readings came from a G6 or G7 transmitter.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


class DexcomError(RuntimeError):
    """Dexcom failures with messages that do not include credentials or response bodies."""


class DexcomBackend:
    TRUSTED_HOSTS = frozenset({
        "api.dexcom.com", "sandbox-api.dexcom.com", "api.dexcom.eu", "api.dexcom.jp",
    })

    def __init__(self, *, client_id: str, client_secret: str, redirect_uri: str,
                 base_url: str, access_token: str | None = None,
                 refresh_token: str | None = None, expires_at: float | None = None,
                 refresh_expires_at: float | None = None,
                 session: requests.Session | None = None, timeout_s: float = 30.0):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.base_url = self._validated_base_url(base_url)
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._refresh_expires_at = refresh_expires_at
        self._token_lock = threading.RLock()
        self.session = session or requests.Session()
        self.timeout_s = timeout_s

    @classmethod
    def _validated_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (parsed.scheme != "https" or parsed.hostname not in cls.TRUSTED_HOSTS
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise DexcomError("base URL must be an HTTPS origin on a trusted Dexcom host")
        return f"https://{parsed.hostname}"

    @classmethod
    def from_env(cls, **kwargs: Any) -> "DexcomBackend":
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        required = ("DEXCOM_CLIENT_ID", "DEXCOM_CLIENT_SECRET", "DEXCOM_REDIRECT_URI", "DEXCOM_BASE_URL")
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise DexcomError("missing configuration: " + ", ".join(missing))
        return cls(client_id=os.environ[required[0]], client_secret=os.environ[required[1]],
                   redirect_uri=os.environ[required[2]], base_url=os.environ[required[3]], **kwargs)

    def authorization_url(self, state: str) -> str:
        return f"{self.base_url}/v3/oauth2/login?" + urlencode({
            "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "response_type": "code", "scope": "offline_access", "state": state,
        })

    def exchange_code(self, code: str) -> str:
        return self._token_request({"grant_type": "authorization_code", "code": code,
                                    "client_id": self.client_id, "client_secret": self.client_secret,
                                    "redirect_uri": self.redirect_uri})

    def refresh_token(self, refresh_token: str) -> str:
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token,
                                    "client_id": self.client_id, "client_secret": self.client_secret,
                                    "redirect_uri": self.redirect_uri})

    def _token_request(self, form: dict[str, str]) -> str:
        try:
            response = self.session.post(f"{self.base_url}/v3/oauth2/token", data=form,
                                         headers={"Accept": "application/json"}, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise DexcomError(f"token request network error: {type(exc).__name__}") from None
        if response.status_code != 200:
            raise DexcomError(f"token request failed (HTTP {response.status_code})")
        try:
            token_data = response.json()
            token = token_data.get("access_token") if isinstance(token_data, dict) else None
        except (ValueError, AttributeError):
            token_data, token = {}, None
        if not token:
            raise DexcomError("token response had no access token")
        try:
            expires_in = float(token_data.get("expires_in"))
        except (TypeError, ValueError):
            expires_in = 0.0
        try:
            refresh_expires_in = float(token_data.get("refresh_expires_in"))
        except (TypeError, ValueError):
            refresh_expires_in = 0.0
        with self._token_lock:
            self._access_token = token
            self._expires_at = time.time() + expires_in if expires_in > 0 else None
            # Dexcom rotates refresh tokens. Retain the new token; if omitted, keep the prior one.
            self._refresh_token = token_data.get("refresh_token") or self._refresh_token
            # Dexcom may return 0 for refresh_expires_in; treat that as unspecified.
            self._refresh_expires_at = (time.time() + refresh_expires_in
                                        if refresh_expires_in > 0 else None)
        return token

    def login(self, *, open_browser: bool = True, wait_s: float = 300) -> str:
        """Run the local OAuth callback flow used by dexcom_sandbox_test.py."""
        redirect = urlparse(self.redirect_uri)
        if (redirect.scheme not in ("http", "https")
                or redirect.hostname not in ("localhost", "127.0.0.1")
                or redirect.username or redirect.password or redirect.query or redirect.fragment):
            raise DexcomError("redirect URI must point at localhost for the local login flow")
        state, result, done = secrets.token_urlsafe(32), {}, threading.Event()
        wanted_path = redirect.path or "/"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler_self):
                parsed = urlparse(handler_self.path)
                query = parse_qs(parsed.query)
                if parsed.path != wanted_path or query.get("state", [None])[0] != state:
                    handler_self.send_error(400, "Invalid OAuth callback")
                    return
                if "error" in query:
                    result["error"] = True
                else:
                    result["code"] = query.get("code", [None])[0]
                handler_self.send_response(200 if result.get("code") else 400)
                handler_self.send_header("Content-Type", "text/html")
                handler_self.end_headers()
                handler_self.wfile.write(b"<h2>Dexcom authorization received. Return to the app.</h2>")
                done.set()

            def log_message(self, *args):
                pass

        server = HTTPServer((redirect.hostname, redirect.port or (443 if redirect.scheme == "https" else 80)), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = self.authorization_url(state)
            if open_browser:
                webbrowser.open(url)
            else:
                print("Open this URL to log in:", url)
            if not done.wait(wait_s):
                raise DexcomError("login timed out")
        finally:
            server.shutdown()
            server.server_close()
        if result.get("error"):
            raise DexcomError("authorization was denied")
        code = result.get("code")
        if not code:
            raise DexcomError("authorization code missing")
        return self.exchange_code(code)

    @property
    def refresh_token_value(self) -> str | None:
        """Current refresh token, including any rotated value. Never log this property."""
        return self._refresh_token

    @property
    def token_expires_at(self) -> float | None:
        """Unix timestamp for the current access-token expiry, when provided by Dexcom."""
        return self._expires_at

    @property
    def refresh_token_expires_at(self) -> float | None:
        """Unix timestamp for refresh-token expiry, when Dexcom provides one."""
        return self._refresh_expires_at

    def _refresh_access_token(self) -> str:
        with self._token_lock:
            if not self._refresh_token:
                raise DexcomError("access token expired and no refresh token is available; log in again")
            refresh = self._refresh_token
            return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh,
                                        "client_id": self.client_id, "client_secret": self.client_secret})

    def get_json(self, path: str, *, params: dict[str, str] | None = None) -> dict:
        if not path.startswith("/v3/") or ".." in path:
            raise DexcomError("invalid Dexcom API path")
        with self._token_lock:
            if not self._access_token:
                raise DexcomError("no access token available; complete OAuth login first")
            if (self._expires_at is not None and self._expires_at <= time.time() + 60
                    and self._refresh_token):
                self._refresh_access_token()

        refreshed_after_401 = False
        while True:
            token = self._access_token
            try:
                response = self.session.get(f"{self.base_url}{path}", params=params,
                                            headers={"Authorization": f"Bearer {token}",
                                                     "Accept": "application/json"}, timeout=self.timeout_s)
            except requests.RequestException as exc:
                raise DexcomError(f"API request network error: {type(exc).__name__}") from None
            if response.status_code == 401 and not refreshed_after_401 and self._refresh_token:
                self._refresh_access_token()
                refreshed_after_401 = True
                continue
            if response.status_code == 401 and refreshed_after_401:
                raise DexcomError("HTTP 401 after token refresh: reauthorization may be required")
            break
        if response.status_code in (401, 403):
            raise DexcomError(f"HTTP {response.status_code}: token expired, revoked or not authorized")
        if response.status_code == 429:
            raise DexcomError("HTTP 429: rate limited, try again later")
        if response.status_code >= 500:
            raise DexcomError(f"HTTP {response.status_code}: Dexcom server error")
        if response.status_code != 200:
            raise DexcomError(f"HTTP {response.status_code}: unexpected response")
        try:
            data = response.json()
        except ValueError:
            raise DexcomError("malformed response (not JSON)") from None
        if not isinstance(data, dict):
            raise DexcomError("malformed response (unexpected shape)")
        return data

    def glucose_records(self, *, days: int = 1, use_data_range: bool = False) -> list[dict]:
        end = datetime.now(timezone.utc)
        if use_data_range:
            data_range = self.get_json("/v3/users/self/dataRange")
            raw_end = ((data_range.get("egvs") or {}).get("end") or {}).get("systemTime")
            if not raw_end:
                raise DexcomError("dataRange has no glucose records")
            end = _parse_time(raw_end)
        start = end - timedelta(days=days)
        data = self.get_json("/v3/users/self/egvs", params={
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        records = data.get("records", data.get("egvs"))
        if not isinstance(records, list):
            raise DexcomError("malformed response (no records list)")
        return records


def _parse_time(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise DexcomError("malformed glucose timestamp") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
