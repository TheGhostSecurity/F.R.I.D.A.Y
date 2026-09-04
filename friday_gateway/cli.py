from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import load_config


def _base_url() -> str:
    return os.environ.get("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")


def _request(path: str, method: str = "GET") -> object:
    request = Request(f"{_base_url()}{path}", method=method)
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise SystemExit(f"gateway returned HTTP {error.code}: {error.read().decode()}") from error


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ask_parser = subparsers.add_parser("ask", help="ask the local Ollama agent")
    ask_parser.add_argument("query")
    subparsers.add_parser("pending")
    for command in ("approve", "deny"):
        item = subparsers.add_parser(command)
        item.add_argument("id")
    config_parser = subparsers.add_parser("config")
    config_parser.add_argument("--file", default=os.environ.get("FRIDAY_CONFIG", "config/permissions.yaml"))
    args = parser.parse_args()

    if args.command == "ask":
        # Import only for this command so permission-management commands do not
        # depend on an Ollama runtime being installed or running.
        from .agent import OllamaAgent

        try:
            print(OllamaAgent().ask(args.query))
        except OSError as error:
            raise SystemExit(
                "Could not reach Ollama or the gateway. Start both services, then retry: "
                f"{error}"
            ) from error
        return
    if args.command == "config":
        config = load_config(Path(args.file))
        print(json.dumps({"filesystem": {"allowed_roots": [str(root) for root in config.filesystem.allowed_roots], "permissions": config.filesystem.permissions}}, indent=2))
        return
    if args.command == "pending":
        print(json.dumps(_request("/confirmations"), indent=2))
        return
    print(json.dumps(_request(f"/confirmations/{args.id}/{args.command}", method="POST"), indent=2))
