"""`horizon-mcp-keys`: issue and revoke per-user API keys in an MCP_USERS_FILE.

    horizon-mcp-keys add alice --file users.json     # prints alice's new key once
    horizon-mcp-keys remove alice --file users.json
    horizon-mcp-keys list --file users.json          # names only

--file defaults to $MCP_USERS_FILE. Restart the server after changing the file.
"""
import argparse
import os
import sys

from .users import UsersFileError, add_user, list_users, remove_user


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="horizon-mcp-keys",
        description="Manage per-user API keys for horizon-mcp's multi-user HTTP mode (MCP_USERS_FILE).",
    )
    file_opt = argparse.ArgumentParser(add_help=False)
    file_opt.add_argument(
        "--file",
        default=os.environ.get("MCP_USERS_FILE") or None,
        help="users file (default: $MCP_USERS_FILE)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", parents=[file_opt], help="add a user and print their new key once")
    add.add_argument("name")
    remove = sub.add_parser("remove", parents=[file_opt], help="remove a user (revokes their key)")
    remove.add_argument("name")
    sub.add_parser("list", parents=[file_opt], help="list user names")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.file:
        print("horizon-mcp-keys: pass --file or set MCP_USERS_FILE.", file=sys.stderr)
        return 2
    try:
        if args.command == "add":
            key = add_user(args.file, args.name)
            print(
                f"Added {args.name!r} to {args.file}. Their API key is printed below and is shown only once:\n"
                "store it securely (e.g. a password manager) and give it only to this user. "
                "It can't be recovered — remove and re-add the user to issue a new one. "
                "Restart the server to apply.",
                file=sys.stderr,
            )
            print(key)
        elif args.command == "remove":
            remove_user(args.file, args.name)
            print(f"Removed {args.name!r} from {args.file}. Restart the server to apply.", file=sys.stderr)
        else:
            for name in list_users(args.file):
                print(name)
    except UsersFileError as exc:
        print(f"horizon-mcp-keys: {exc}", file=sys.stderr)
        return 1
    return 0


def main_cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_cli()
