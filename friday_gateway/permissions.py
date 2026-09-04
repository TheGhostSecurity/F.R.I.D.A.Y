from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

from .config import GatewayConfig, VALID_ACTIONS
from .pending import PendingConfirmations

T = TypeVar("T")


class PathRejected(ValueError):
    pass


@dataclass(frozen=True)
class PermissionDecision:
    state: str
    action: str
    resource: str
    confirmation_id: str | None = None
    reason: str | None = None


class Gateway:
    """The sole authorization entry point for every filesystem tool operation."""

    def __init__(self, config: GatewayConfig, confirmations: PendingConfirmations | None = None) -> None:
        self.config = config
        self.confirmations = confirmations or PendingConfirmations()

    def resolve_resource(self, resource: str) -> Path:
        requested = Path(resource).expanduser()
        if not requested.is_absolute():
            # A relative resource is always rooted at an explicitly allowed root,
            # never at the gateway process working directory.
            requested = self.config.filesystem.allowed_roots[0] / requested
        resolved = requested.resolve(strict=False)
        if not any(resolved.is_relative_to(root) for root in self.config.filesystem.allowed_roots):
            raise PathRejected("resolved path is outside filesystem.allowed_roots")
        return resolved

    def check_permission(
        self, action: str, resource: str, confirmation_id: str | None = None
    ) -> PermissionDecision:
        """Authorize a request; every filesystem operation must call this first."""
        if action not in VALID_ACTIONS:
            return PermissionDecision("denied", action, resource, reason="unknown filesystem action")
        try:
            resolved = self.resolve_resource(resource)
        except PathRejected as error:
            return PermissionDecision("denied", action, resource, reason=str(error))

        canonical = str(resolved)
        policy = self.config.filesystem.permissions[action]
        if policy == "deny":
            return PermissionDecision("denied", action, canonical, reason="denied by permission policy")
        if policy == "allow":
            return PermissionDecision("allowed", action, canonical)
        if confirmation_id and self.confirmations.consume_approval(confirmation_id, action, canonical):
            return PermissionDecision("allowed", action, canonical, confirmation_id=confirmation_id)
        confirmation = self.confirmations.create(action, canonical)
        return PermissionDecision("pending_confirmation", action, canonical, confirmation.id)

    def execute(
        self, action: str, resource: str, operation: Callable[[Path], T], confirmation_id: str | None = None
    ) -> tuple[PermissionDecision, T | None]:
        """Mandatory executor wrapper. The callback cannot run before authorization."""
        decision = self.check_permission(action, resource, confirmation_id)
        if decision.state != "allowed":
            return decision, None
        return decision, operation(Path(decision.resource))
