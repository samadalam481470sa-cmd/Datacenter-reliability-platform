"""Push validated JSONL sensor readings to a running RackHelm API.

Only works with an explicit local filepath and a configured secret. Examples:

RACKHELM_OPERATOR_KEY='YOUR_PRIVATE_32_PLUS_CHAR_KEY' \\
  python scripts/import_jsonl.py ./sensors.jsonl --url http://127.0.0.1:8000

Supported JSONL shape: each line is one ReadingIn schema (see /docs).
This importer does not pull BMC/IPMI credentials or change physical infrastructure.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description="Import authenticated rack telemetry from JSONL")
    parser.add_argument("path", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    target = urlparse(args.url)
    if target.scheme not in ("http", "https") or not target.hostname or target.username:
        raise SystemExit("Invalid destination URL")
    if target.scheme == "http" and target.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Remote telemetry submissions require HTTPS")
    key = os.getenv("RACKHELM_OPERATOR_KEY", "")
    if len(key) < 32:
        raise SystemExit("Set RACKHELM_OPERATOR_KEY in the environment; never paste a key into code")
    if not args.path.is_file() or args.path.stat().st_size > 10_000_000:
        raise SystemExit("Input must exist and be smaller than 10 MB")
    records = []
    for line in args.path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
        if len(records) > 10000:
            raise SystemExit("More than 10,000 rows — split into smaller files")
    if not records:
        raise SystemExit("No readings found")
    for offset in range(0, len(records), 200):
        chunk = {"readings": records[offset:offset+200]}
        payload = json.dumps(chunk, allow_nan=False).encode("utf-8")
        request = Request(
            args.url.rstrip("/") + "/api/v1/telemetry/batch", data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": key}, method="POST",
        )
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
        print(f"batch {offset//200 + 1}: inserted={result['inserted']} duplicates={result['duplicate']}")


if __name__ == "__main__":
    main()