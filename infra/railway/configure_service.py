"""Apply explicit service settings through an already authenticated official Railway CLI.

This does not create services, set secrets, choose a billing plan, or deploy code.
The JSON files are GraphQL input manifests, not deprecated railway.json files.
"""

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-id", required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--kind", choices=("backend", "web"), required=True)
    parser.add_argument("--railway", default="railway")
    args = parser.parse_args()
    executable = shutil.which(args.railway)
    if not executable:
        parser.error("Official Railway CLI not found. Install @railway/cli and log in first.")
    settings = json.loads(
        Path(__file__).with_name(f"{args.kind}.service.json").read_text(encoding="utf-8")
    )
    query = (
        "mutation($service:String!,$env:String!,$input:ServiceInstanceUpdateInput!){"
        "serviceInstanceUpdate(serviceId:$service,environmentId:$env,input:$input)}"
    )
    result = subprocess.run(
        [executable, "api", query, "--variables", "@-", "--compact"],
        input=json.dumps(
            {"service": args.service_id, "env": args.environment_id, "input": settings}
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit(f"Railway service configuration failed: {result.stderr}")
    response = json.loads(result.stdout)
    if response.get("errors") or not response.get("data", {}).get("serviceInstanceUpdate"):
        raise SystemExit("Railway did not confirm the service settings; inspect its dashboard.")
    print(f"{args.kind}: service settings applied. Variables and source deployment are separate.")


if __name__ == "__main__":
    main()
