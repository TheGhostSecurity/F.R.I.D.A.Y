from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .permissions import Gateway, PermissionDecision

MAX_RESULTS = 50
MAX_READ_BYTES = 1_000_000

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "search_files", "description": "Search file names and text inside permitted filesystem roots.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Literal text to find."}, "root": {"type": ["string", "null"], "description": "Optional permitted root or path below one."}}, "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 text file inside a permitted filesystem root.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or replace a UTF-8 text file inside a permitted filesystem root. Changes may require approval.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "confirmation_id": {"type": ["string", "null"], "description": "Use only after user approval."}}, "required": ["path", "content"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_recent", "description": "List permitted files modified in a recent time window.", "parameters": {"type": "object", "properties": {"root": {"type": ["string", "null"]}, "hours": {"type": "integer", "minimum": 1, "maximum": 8760, "default": 24}}, "additionalProperties": False}}},
]


def _decision_payload(decision: PermissionDecision, result: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"state": decision.state, "action": decision.action, "resource": decision.resource}
    if decision.confirmation_id:
        payload["confirmation_id"] = decision.confirmation_id
    if decision.reason:
        payload["reason"] = decision.reason
    if decision.state == "allowed":
        payload["result"] = result
    return payload


class FilesystemTools:
    """Tool implementations reachable only through Gateway.execute()."""

    def __init__(self, gateway: Gateway, rg_binary: str | None = None) -> None:
        self.gateway = gateway
        bundled = Path(__file__).parents[1] / ".tools/ripgrep/usr/bin/rg"
        self.rg_binary = rg_binary or os.environ.get("FRIDAY_RG") or (str(bundled) if bundled.is_file() else shutil.which("rg"))

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "search_files": self.search_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_recent": self.list_recent,
        }
        if name not in handlers:
            return {"state": "denied", "reason": f"unknown tool: {name}"}
        try:
            return handlers[name](**arguments)
        except (TypeError, ValueError) as error:
            return {"state": "error", "reason": str(error)}
        except OSError as error:
            return {"state": "error", "reason": str(error)}

    def _roots(self, root: str | None) -> list[str]:
        if root is not None:
            return [root]
        return [str(item) for item in self.gateway.config.filesystem.allowed_roots]

    def _safe_file(self, candidate: Path) -> Path | None:
        try:
            resolved = candidate.resolve(strict=False)
            if any(resolved.is_relative_to(root) for root in self.gateway.config.filesystem.allowed_roots):
                return resolved
        except OSError:
            pass
        return None

    def search_files(self, query: str, root: str | None = None) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not self.rg_binary:
            return {"state": "error", "reason": "ripgrep is not installed; set FRIDAY_RG or install rg"}
        all_matches: dict[Path, int] = {}
        for requested_root in self._roots(root):
            def search(allowed_root: Path) -> None:
                if not allowed_root.is_dir():
                    return
                # --json makes paths unambiguous and --fixed-strings prevents a model
                # supplied query from becoming a regular expression.
                command = [self.rg_binary, "--json", "--ignore-case", "--fixed-strings", "--no-messages", query, "."]
                completed = subprocess.run(command, cwd=allowed_root, capture_output=True, text=True, timeout=15, check=False)
                for line in completed.stdout.splitlines():
                    event = json.loads(line)
                    if event.get("type") != "match":
                        continue
                    relative = event["data"]["path"]["text"]
                    candidate = self._safe_file(allowed_root / relative)
                    if candidate and candidate.is_file():
                        all_matches[candidate] = all_matches.get(candidate, 0) + 1
                # Filename search is intentionally Python-side, avoiding glob syntax.
                files = subprocess.run([self.rg_binary, "--files", "--no-messages"], cwd=allowed_root, capture_output=True, text=True, timeout=15, check=False)
                for relative in files.stdout.splitlines():
                    candidate = self._safe_file(allowed_root / relative)
                    if candidate and candidate.is_file() and query.casefold() in candidate.name.casefold():
                        all_matches[candidate] = all_matches.get(candidate, 0) + 1

            decision, _ = self.gateway.execute("read", requested_root, search)
            if decision.state != "allowed":
                return _decision_payload(decision)

        ranked = sorted(all_matches.items(), key=lambda item: (-item[1], -item[0].stat().st_mtime, str(item[0])))[:MAX_RESULTS]
        return {"state": "allowed", "results": [{"path": str(path), "matches": count, "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()} for path, count in ranked]}

    def read_file(self, path: str) -> dict[str, Any]:
        def read(allowed_path: Path) -> dict[str, Any]:
            if not allowed_path.is_file():
                raise ValueError("path is not a regular file")
            if allowed_path.stat().st_size > MAX_READ_BYTES:
                raise ValueError(f"file exceeds {MAX_READ_BYTES} byte read limit")
            return {"path": str(allowed_path), "content": allowed_path.read_text(encoding="utf-8", errors="replace")}

        decision, result = self.gateway.execute("read", path, read)
        return _decision_payload(decision, result)

    def write_file(self, path: str, content: str, confirmation_id: str | None = None) -> dict[str, Any]:
        # Decide create/modify from the canonical target; either route still goes
        # through Gateway.execute before open/write occurs.
        try:
            target = self.gateway.resolve_resource(path)
        except ValueError:
            # Preserve the gateway's canonical denial response rather than leaking
            # a resolver exception through a concrete tool implementation.
            return _decision_payload(self.gateway.check_permission("create", path, confirmation_id))
        action = "modify" if target.exists() else "create"

        def write(allowed_path: Path) -> dict[str, Any]:
            if allowed_path.exists() and not allowed_path.is_file():
                raise ValueError("path is not a regular file")
            allowed_path.write_text(content, encoding="utf-8")
            return {"path": str(allowed_path), "bytes_written": len(content.encode("utf-8"))}

        decision, result = self.gateway.execute(action, path, write, confirmation_id)
        return _decision_payload(decision, result)

    def list_recent(self, root: str | None = None, hours: int = 24) -> dict[str, Any]:
        if not isinstance(hours, int) or not 1 <= hours <= 8760:
            raise ValueError("hours must be an integer from 1 through 8760")
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        results: list[Path] = []
        for requested_root in self._roots(root):
            def collect(allowed_root: Path) -> None:
                if not allowed_root.is_dir():
                    return
                for directory, dirs, names in os.walk(allowed_root, followlinks=False):
                    dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
                    for name in names:
                        candidate = self._safe_file(Path(directory) / name)
                        if candidate and candidate.is_file() and datetime.fromtimestamp(candidate.stat().st_mtime, UTC) >= cutoff:
                            results.append(candidate)

            decision, _ = self.gateway.execute("read", requested_root, collect)
            if decision.state != "allowed":
                return _decision_payload(decision)
        results.sort(key=lambda path: (-path.stat().st_mtime, str(path)))
        return {"state": "allowed", "results": [{"path": str(path), "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(), "size": path.stat().st_size} for path in results[:MAX_RESULTS]]}
