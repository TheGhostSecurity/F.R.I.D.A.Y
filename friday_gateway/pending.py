from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4


@dataclass
class Confirmation:
    id: str
    action: str
    resource: str
    status: str
    created_at: str


class PendingConfirmations:
    """Thread-safe, in-memory confirmation queue for the single gateway process."""

    def __init__(self) -> None:
        self._items: dict[str, Confirmation] = {}
        self._lock = Lock()

    def create(self, action: str, resource: str) -> Confirmation:
        item = Confirmation(
            id=str(uuid4()), action=action, resource=resource, status="pending",
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._items[item.id] = item
        return item

    def list_pending(self) -> list[dict[str, str]]:
        with self._lock:
            return [asdict(item) for item in self._items.values() if item.status == "pending"]

    def decide(self, confirmation_id: str, approve: bool) -> Confirmation | None:
        with self._lock:
            item = self._items.get(confirmation_id)
            if item is None or item.status != "pending":
                return None
            item.status = "approved" if approve else "denied"
            return item

    def consume_approval(self, confirmation_id: str, action: str, resource: str) -> bool:
        """One approved request authorizes exactly its original action and resource once."""
        with self._lock:
            item = self._items.get(confirmation_id)
            if item is None or item.status != "approved":
                return False
            if item.action != action or item.resource != resource:
                return False
            item.status = "consumed"
            return True
