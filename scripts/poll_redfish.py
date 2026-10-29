"""Read-only Redfish collector that pushes observations to RackHelm FleetOS.

Run in a private management network, never against public internet endpoints.
No physical control commands are implemented.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from rackhelm.redfish import collect, load_config


def poll(config_path: Path, *, dry_run: bool = False) -> int:
    config = load_config(config_path)
    readings = []
    failures = 0
    for endpoint in config.endpoints:
        try:
            reading = collect(endpoint)
            readings.append(reading)
            print(f"{endpoint.rack_id}: received temperature/power/fan measurements", file=sys.stderr)
        except Exception as exc:
            failures += 1
            # Never include exception strings: they may contain credential-bearing URLs.
            print(f"{endpoint.rack_id}: collection failed ({type(exc).__name__})", file=sys.stderr)
    if dry_run:
        print(json.dumps({"readings": [r.model_dump(mode="json") for r in readings]}))
        return 1 if failures else 0
    key = os.getenv("RACKHELM_OPERATOR_KEY", "")
    if len(key) < 32:
        raise ValueError("RACKHELM_OPERATOR_KEY must be set (32+ characters)")
    if readings:
        data = json.dumps({"readings": [r.model_dump(mode="json") for r in readings]}).encode()
        req = Request(config.rackhelm_url + "/api/v1/telemetry/batch", data=data,
                      headers={"X-API-Key": key, "Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=15) as response:
            print(json.dumps(json.load(response)))
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Redfish server telemetry collector")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Collect and print without posting")
    parser.add_argument("--interval", type=int, default=0, help="Repeat every N seconds; 0 = once")
    args = parser.parse_args()
    if args.interval and not 30 <= args.interval <= 3600:
        parser.error("Interval must be 30-3600 seconds")
    while True:
        code = poll(args.config, dry_run=args.dry_run)
        if not args.interval:
            raise SystemExit(code)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()