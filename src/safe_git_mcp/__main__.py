import argparse
import sys
from pathlib import Path

from .config import Policy
from .server import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Policy-filtered Git MCP stdio prototype")
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    try:
        create_server(Policy.load(args.policy)).run(transport="stdio")
    except KeyboardInterrupt:
        pass
    except Exception:
        sys.stderr.write(
            '{"code":"INTERNAL_ERROR","message":"Server could not start or continue."}\n'
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
