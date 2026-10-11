import argparse
import json
from pathlib import Path

from treasurypilot_api.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the TreasuryPilot OpenAPI schema.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
