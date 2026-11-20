"""Print a small, one-shot diagnostic summary from the local dashboard API."""
from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Request /api/summary and print selected diagnostic fields."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8000/api/summary",
        help="summary endpoint URL (default: %(default)s)",
    )
    args = parser.parse_args()

    try:
        with urlopen(args.url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"Request failed: HTTP {exc.code}")
        return 1
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Request failed: {type(exc).__name__}")
        return 1

    if not isinstance(payload, dict):
        print("Request failed: unexpected response shape")
        return 1

    history = payload.get("glucose_history")
    history_count = len(history) if isinstance(history, list) else 0
    latest = payload.get("glucose_mgdl")
    age = payload.get("glucose_age_seconds")

    print(f"mode: {payload.get('mode')}")
    print(f"status: {payload.get('status')}")
    print(f"latest glucose: {latest if isinstance(latest, (int, float)) else 'unavailable'}")
    print(f"age seconds: {age if isinstance(age, (int, float)) else 'unavailable'}")
    print(f"history points: {history_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
