
import os
import secrets
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("DEXCOM_CLIENT_ID")
CLIENT_SECRET = os.getenv("DEXCOM_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DEXCOM_REDIRECT_URI")
BASE_URL = os.getenv("DEXCOM_BASE_URL", "").rstrip("/")

AUTH_URL = f"{BASE_URL}/v3/oauth2/login"
TOKEN_URL = f"{BASE_URL}/v3/oauth2/token"
EGV_URL = f"{BASE_URL}/v3/users/self/egvs"

authorization_code = None
state = secrets.token_urlsafe(32)


class CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        global authorization_code

        params = parse_qs(urlparse(self.path).query)

        if params.get("state", [None])[0] != state:
            self.send_error(400, "Invalid OAuth state")
            return

        if "error" in params:
            self.send_error(400, "Dexcom authorization was denied")
            return

        authorization_code = params.get("code", [None])[0]

        if not authorization_code:
            self.send_error(400, "Authorization code missing")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<h2>Dexcom authorization received.</h2>"
            b"<p>Return to PyCharm.</p>"
        )

    def log_message(self, format, *args):
        pass


def exchange_token(code):

    print("\nExchanging authorization code for access token...")

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post(
        TOKEN_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        },
        timeout=30
    )

    if response.status_code != 200:
        print("Token exchange failed.")
        print("HTTP status:", response.status_code)
        return None

    token_data = response.json()

    access_token = token_data.get("access_token")

    if not access_token:
        print("No access token returned.")
        return None

    print("Access token successfully obtained.")
    print("Token type:", token_data.get("token_type"))
    print("Expires in:", token_data.get("expires_in"), "seconds")

    return access_token


def get_glucose_data(access_token):

    print("\nRequesting Dexcom glucose readings...")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=30)

    params = {
        "startDate": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "endDate": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = requests.get(
        EGV_URL,
        headers=headers,
        params=params,
        timeout=30
    )

    if response.status_code != 200:
        print("Glucose request failed.")
        print("HTTP status:", response.status_code)
        return

    data = response.json()
    records = data.get("records", [])

    print("\nDexcom API connection successful!")
    print("Number of glucose records:", len(records))

    for record in records[-5:]:

        print(
            "Time:", record.get("systemTime"),
            "| Glucose:", record.get("value"),
            record.get("unit"),
            "| Trend:", record.get("trend")
        )

    if not records:
        print("No readings found in this date window.")


def main():

    if not all([
        CLIENT_ID,
        CLIENT_SECRET,
        REDIRECT_URI,
        BASE_URL
    ]):
        raise RuntimeError(
            "Missing Dexcom configuration in .env"
        )

    server = HTTPServer(
        ("localhost", 8000),
        CallbackHandler
    )

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "offline_access",
        "state": state,
    }

    url = AUTH_URL + "?" + urlencode(params)

    threading.Thread(
        target=server.serve_forever,
        daemon=True
    ).start()

    print("Opening Dexcom Sandbox login...")

    webbrowser.open(url)

    try:
        while authorization_code is None:
            threading.Event().wait(0.5)

    except KeyboardInterrupt:
        print("Authorization cancelled.")
        return

    finally:
        server.shutdown()
        server.server_close()

    access_token = exchange_token(authorization_code)

    if access_token:
        get_glucose_data(access_token)


if __name__ == "__main__":
    main()
