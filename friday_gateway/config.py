from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Permission = Literal["allow", "ask", "deny"]
VALID_ACTIONS = frozenset({"read", "create", "modify", "delete"})
VALID_PERMISSIONS = frozenset({"allow", "ask", "deny"})


@dataclass(frozen=True)
class FilesystemPolicy:
    allowed_roots: tuple[Path, ...]
    permissions: dict[str, Permission]


@dataclass(frozen=True)
class GatewayConfig:
    filesystem: FilesystemPolicy


def load_config(path: str | Path) -> GatewayConfig:
    config_path = Path(path).expanduser()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    filesystem = raw.get("filesystem")
    if not isinstance(filesystem, dict):
        raise ValueError("permissions config requires a 'filesystem' mapping")
    roots = filesystem.get("allowed_roots")
    permissions = filesystem.get("permissions")
    if not isinstance(roots, list) or not roots or not all(isinstance(root, str) for root in roots):
        raise ValueError("filesystem.allowed_roots must be a non-empty list of paths")
    if not isinstance(permissions, dict):
        raise ValueError("filesystem.permissions must be a mapping")

    invalid = set(permissions) - VALID_ACTIONS
    missing = VALID_ACTIONS - set(permissions)
    if invalid or missing:
        raise ValueError(f"permissions must define exactly {sorted(VALID_ACTIONS)}")
    if any(value not in VALID_PERMISSIONS for value in permissions.values()):
        raise ValueError("permission values must be allow, ask, or deny")

    # strict=False resolves every existing symlink in a path while still supporting
    # paths that do not exist yet (needed for create authorization).
    resolved_roots = tuple(Path(root).expanduser().resolve(strict=False) for root in roots)
    return GatewayConfig(FilesystemPolicy(resolved_roots, dict(permissions)))
