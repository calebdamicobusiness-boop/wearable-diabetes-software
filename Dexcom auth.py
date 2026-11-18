"""Dexcom OAuth login and automatic token refresh.

Built from dexcom_sandbox_test.py (which proved the login works) with three changes:
  1. Tokens are SAVED, including the refresh token, so you log in once, not every run.
  2. access_token() refreshes an expired token by itself. Pass it to DexcomSource as the
     token_provider.
  3. Failures raise DexcomAuthError (a DexcomError), which pipeline.poll() already handles.

Credentials come from .env (never committed). Required names:
  DEXCOM_CLIENT_ID, DEXCOM_CLIENT_SECRET, DEXCOM_REDIRECT_URI, DEXCOM_BASE_URL

Tokens are stored outside the repo (default ~/.wearables/dexcom_tokens.json). NOTE for S1
(AES-256 at rest): that file is plaintext. Never put it in Git or OneDrive. Before real
accounts are used, encrypt it or move it to the OS credential store.
"""
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Optional

from dexcom_source import DexcomError

REFRESH_MARGIN_S = 60          # refresh a minute before the token actually expires


class DexcomAuthError(DexcomError):
    """Login or refresh failed. Messages never contain tokens, secrets or response bodies."""


class TokenStore:
    """JSON file written atomically with owner-only permissions (best effort on Windows)."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or os.environ.get("DEXCOM_TOKEN_FILE")
                         or Path.home() / ".wearables" / "dexcom_tokens.json")

    def load(self) -> Optional[dict]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return None

    def save(self, tokens: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")          # write-then-replace: a crash can't leave half a file
        tmp.write_text(json.dumps(tokens))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


HttpPost = Callable[[str, dict, float], "tuple[int, str]"]


def _urllib_post(url: str, form: dict, timeout: float) -> "tuple[int, str]":
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(form).encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DexcomAuthError(f"network error: {type(e).__name__}") from None


class DexcomAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, base_url: str,
                 store: Optional[TokenStore] = None, http_post: Optional[HttpPost] = None,
                 clock: Callable[[], float] = time.time, timeout_s: float = 30.0):
        self.client_id, self.client_secret = client_id, client_secret
        self.redirect_uri, self.base_url = redirect_uri, base_url.rstrip("/")
        self.store = store or TokenStore()
        self.http_post = http_post or _urllib_post
        self.clock, self.timeout_s = clock, timeout_s

    @classmethod
    def from_env(cls, **kw) -> "DexcomAuth":
        try:                                           # optional: read .env if python-dotenv is installed
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        names = ("DEXCOM_CLIENT_ID", "DEXCOM_CLIENT_SECRET", "DEXCOM_REDIRECT_URI", "DEXCOM_BASE_URL")
        missing = [n for n in names if not os.getenv(n)]
        if missing:
            raise DexcomAuthError("missing in .env: " + ", ".join(missing))   # names only, never values
        return cls(*(os.environ[n] for n in names), **kw)

    # --------------------------------------------------------------- tokens
    def has_tokens(self) -> bool:
        t = self.store.load()
        return bool(t and (t.get("refresh_token") or t.get("access_token")))

    def _token_request(self, form: dict) -> dict:
        status, body = self.http_post(f"{self.base_url}/v3/oauth2/token", form, self.timeout_s)
        if status != 200:
            raise DexcomAuthError(f"token request failed (HTTP {status})")
        try:
            data = json.loads(body)
        except ValueError:
            raise DexcomAuthError("token response was not JSON") from None
        if not isinstance(data, dict) or not data.get("access_token"):
            raise DexcomAuthError("token response had no access token")
        return data

    def _save(self, data: dict, previous_refresh: Optional[str] = None) -> dict:
        tokens = {
            "access_token": data["access_token"],
            # Keep the newest refresh token. If Dexcom sends none, keep the old one.
            "refresh_token": data.get("refresh_token") or previous_refresh,
            "expires_at": self.clock() + int(data.get("expires_in") or 0),
        }
        self.store.save(tokens)
        return tokens

    def access_token(self) -> str:
        """Use as DexcomSource(token_provider=auth.access_token). Refreshes when needed."""
        tokens = self.store.load()
        if not tokens:
            raise DexcomAuthError("not logged in: run login() once")
        if tokens.get("access_token") and self.clock() < tokens.get("expires_at", 0) - REFRESH_MARGIN_S:
            return tokens["access_token"]
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise DexcomAuthError("token expired and no refresh token saved: run login() again")
        try:
            data = self._token_request({
                "grant_type": "refresh_token", "refresh_token": refresh,
                "client_id": self.client_id, "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri})
        except DexcomAuthError as e:
            raise DexcomAuthError(f"{e}; run login() again if this keeps happening") from None
        return self._save(data, previous_refresh=refresh)["access_token"]

    # ---------------------------------------------------------------- login
    def login(self, wait_s: float = 300, open_browser: bool = True) -> None:
        """Browser login. The redirect URI must be http://localhost:<port>/<path> and must
        match the one registered in the Dexcom developer portal exactly."""
        u = urllib.parse.urlparse(self.redirect_uri)
        if u.hostname not in ("localhost", "127.0.0.1"):
            raise DexcomAuthError("redirect URI must point at localhost for the local login flow")
        state, result, done = secrets.token_urlsafe(32), {}, threading.Event()
        want_path = u.path or "/"

        class Handler(BaseHTTPRequestHandler):
            def _page(self, text: str):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<h2>{text}</h2><p>You can close this tab.</p>".encode())

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != want_path:                 # e.g. the browser asking for /favicon.ico
                    self.send_error(404)
                    return
                q = urllib.parse.parse_qs(parsed.query)
                if q.get("state", [None])[0] != state:
                    self.send_error(400, "Invalid OAuth state")
                    return
                if "error" in q:
                    result["error"] = True
                    self._page("Dexcom authorization was denied.")
                elif q.get("code", [None])[0]:
                    result["code"] = q["code"][0]
                    self._page("Dexcom authorization received.")
                else:
                    self.send_error(400, "Authorization code missing")
                    return
                done.set()

            def log_message(self, *a):
                pass

        server = HTTPServer((u.hostname, u.port or 80), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"{self.base_url}/v3/oauth2/login?" + urllib.parse.urlencode({
                "client_id": self.client_id, "redirect_uri": self.redirect_uri,
                "response_type": "code", "scope": "offline_access", "state": state})
            if open_browser:
                webbrowser.open(url)
            else:
                print("Open this URL to log in:", url)
            if not done.wait(wait_s):
                raise DexcomAuthError("login timed out")     # the old script waited forever here
        finally:
            server.shutdown()
            server.server_close()
        if result.get("error"):
            raise DexcomAuthError("authorization was denied")
        self._save(self._token_request({
            "grant_type": "authorization_code", "code": result["code"],
            "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri}))