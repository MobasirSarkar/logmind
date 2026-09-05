import argparse
import json
import sys

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="simulator", description="LogMind Synthetic Incident Simulator CLI"
    )
    parser.add_argument(
        "--url", default="http://127.0.0.1:8000", help="Base URL of LogMind API"
    )
    parser.add_argument(
        "--api-key", default="lmd_dev_key", help="API Key for LogMind API"
    )
    parser.add_argument("--tenant", default="tenant-default", help="Tenant ID")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Start
    start_parser = subparsers.add_parser("start", help="Start continuous background traffic")
    start_parser.add_argument(
        "--rate", type=int, default=20, help="Log emission rate per second"
    )

    # Stop
    subparsers.add_parser("stop", help="Stop continuous background traffic")

    # Trigger
    trigger_parser = subparsers.add_parser(
        "trigger", help="Inject a failure incident scenario"
    )
    trigger_parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario type: PAYMENT_TIMEOUT | DB_POOL_EXHAUSTION | AUTH_DEPENDENCY_FAILURE | RETRY_STORM",
    )
    trigger_parser.add_argument(
        "--duration", type=int, default=30, help="Duration in seconds"
    )
    trigger_parser.add_argument(
        "--intensity", type=float, default=1.0, help="Failure intensity multiplier"
    )

    # Status
    subparsers.add_parser("status", help="Get current simulator status")

    # Run inspection
    run_parser = subparsers.add_parser(
        "run", help="Inspect a specific scenario run record"
    )
    run_parser.add_argument("run_id", help="Scenario run ID")

    args = parser.parse_args()

    headers = {
        "X-API-Key": args.api_key,
        "X-Tenant-ID": args.tenant,
        "Content-Type": "application/json",
    }
    base_url = args.url.rstrip("/")

    with httpx.Client(timeout=15.0) as client:
        try:
            if args.command == "start":
                res = client.post(
                    f"{base_url}/api/v1/simulator/start",
                    headers=headers,
                    json={"tenant_id": args.tenant, "rate_per_sec": args.rate},
                )
            elif args.command == "stop":
                res = client.post(f"{base_url}/api/v1/simulator/stop", headers=headers)
            elif args.command == "trigger":
                res = client.post(
                    f"{base_url}/api/v1/simulator/scenarios/trigger",
                    headers=headers,
                    json={
                        "scenario_type": args.scenario,
                        "tenant_id": args.tenant,
                        "duration_seconds": args.duration,
                        "intensity": args.intensity,
                    },
                )
            elif args.command == "status":
                res = client.get(f"{base_url}/api/v1/simulator/status", headers=headers)
            elif args.command == "run":
                res = client.get(
                    f"{base_url}/api/v1/simulator/runs/{args.run_id}", headers=headers
                )
            else:
                parser.print_help()
                sys.exit(1)

            if res.status_code >= 400:
                print(f"Error ({res.status_code}): {res.text}", file=sys.stderr)
                sys.exit(1)

            print(json.dumps(res.json(), indent=2))
        except httpx.RequestError as exc:
            print(f"Connection error to {base_url}: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
