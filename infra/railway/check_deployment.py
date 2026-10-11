"""Read-only cloud smoke check. No logins, event creation, passwords or writes."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


def origin(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Use an origin without credentials, query or fragment")
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or (
        parts.scheme != "https" and not (local and parts.scheme == "http")
    ):
        raise ValueError("Use HTTPS; HTTP is allowed only for localhost checks")
    if parts.path.rstrip("/") not in {"", "/api/v1"}:
        raise ValueError("Use only the service origin or its /api/v1 address")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def get(url: str) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": "DriverGuard-DeploymentCheck/1"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read(100_000)
    except HTTPError as error:
        return error.code, error.read(100_000)


def check(api: str, web: str) -> list[tuple[str, bool]]:
    results: list[tuple[str, bool]] = []
    status, body = get(api + "/api/v1/health")
    live = json.loads(body) if status == 200 else {}
    results.append(
        ("API process", status == 200 and live.get("service") == "driverguard-backend")
    )
    status, body = get(api + "/api/v1/health/ready")
    ready = json.loads(body) if status == 200 else {}
    results.append(
        (
            "Database and object storage",
            status == 200
            and all(
                ready.get(key) == expected
                for key, expected in (
                    ("status", "ready"),
                    ("db", "ok"),
                    ("storage", "ok"),
                )
            ),
        )
    )
    status, _ = get(api + "/api/v1/drivers")
    results.append(("Driver directory requires authentication", status in {401, 403}))
    status, body = get(web + "/login")
    results.append(("Coordinator login page", status == 200 and b"DriverGuard" in body))
    status, body = get(web + "/driver/login")
    results.append(("Driver login page", status == 200 and b"DriverGuard" in body))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--web", required=True)
    args = parser.parse_args()
    try:
        results = check(origin(args.api), origin(args.web))
    except (ValueError, OSError, URLError):
        print("FAIL: invalid address, unreachable service, or non-JSON API response")
        return 1
    for label, passed in results:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    print(
        "This does not prove login, photo upload or phone-to-dashboard event sync; "
        "test them separately."
    )
    return 0 if all(passed for _, passed in results) else 1


if __name__ == "__main__":
    sys.exit(main())
