import argparse
import json
import sys
from pathlib import Path

from .config import Policy, apply_project_denies


def main() -> None:
    parser = argparse.ArgumentParser(description="Policy-filtered Git MCP stdio prototype")
    parser.add_argument("--policy", type=Path, help="Serve MCP stdio using this policy")
    commands = parser.add_subparsers(dest="command")
    diagnostics = commands.add_parser("doctor", help="Check policy, startup and MCP connection")
    diagnostics.add_argument("--policy", type=Path, required=True)
    install = commands.add_parser(
        "setup", help="Create/reuse a per-project policy and check startup"
    )
    install.add_argument("--repo", type=Path, required=True)
    install.add_argument("--name", required=True)
    install.add_argument("--config-dir", type=Path, default=Path("~/.config/safe-git-mcp"))
    install.add_argument(
        "--client", default="eltex-claude", help="Client executable (no shell arguments)"
    )
    install.add_argument(
        "--register", action="store_true", help="Write registration using the client CLI"
    )
    args = parser.parse_args()
    if args.command:
        from .deployment import MESSAGES, DeploymentError, doctor, setup

        try:
            result = (
                doctor(args.policy)
                if args.command == "doctor"
                else setup(args.repo, args.name, args.config_dir, args.client, args.register)
            )
            print(json.dumps(result))
        except DeploymentError as exc:
            print(json.dumps({"ok": False, "code": exc.code, "message": str(exc)}))
            raise SystemExit(1) from None
        except Exception:
            print(
                json.dumps(
                    {"ok": False, "code": "SETUP_FAILED", "message": MESSAGES["SETUP_FAILED"]}
                )
            )
            raise SystemExit(1) from None
        return
    if args.policy is None:
        parser.error("--policy is required to serve MCP; see setup --help or doctor --help")
    try:
        from .server import create_server

        create_server(apply_project_denies(Policy.load(args.policy.expanduser().absolute()))).run(
            transport="stdio"
        )
    except KeyboardInterrupt:
        pass
    except Exception:
        sys.stderr.write(
            '{"code":"INTERNAL_ERROR","message":"Server could not start or continue."}\n'
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
