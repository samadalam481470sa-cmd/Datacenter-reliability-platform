"""Command-line bootstrap and verification for local operators."""

from __future__ import annotations

import argparse
import json

from rackhelm import service, store


def main() -> None:
    parser = argparse.ArgumentParser(description="RackHelm FleetOS operations")
    parser.add_argument("action", choices=["seed", "audit", "overview", "incidents"])
    args = parser.parse_args()
    store.initialize()
    if args.action == "seed":
        print("Synthetic fleet inventory initialized")
    elif args.action == "audit":
        print(json.dumps(store.audit_valid(), indent=2))
    elif args.action == "overview":
        print(json.dumps(service.dashboard_state()["kpis"], indent=2))
    elif args.action == "incidents":
        print(json.dumps(store.incidents(), indent=2))


if __name__ == "__main__":
    main()