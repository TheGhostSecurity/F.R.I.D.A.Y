from pathlib import Path

import pytest

from friday_gateway.config import load_config
from friday_gateway.permissions import Gateway


def write_config(tmp_path: Path, root: Path, permissions: dict[str, str] | None = None) -> Gateway:
    config_file = tmp_path / "permissions.yaml"
    config_file.write_text(
        "filesystem:\n"
        f"  allowed_roots:\n    - {root}\n"
        "  permissions:\n"
        + "\n".join(f"    {action}: {value}" for action, value in (permissions or {"read": "allow", "create": "allow", "modify": "ask", "delete": "ask"}).items())
        + "\n",
        encoding="utf-8",
    )
    return Gateway(load_config(config_file))


def test_relative_dotdot_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    gateway = write_config(tmp_path, root)
    decision = gateway.check_permission("read", "../../etc/passwd")
    assert decision.state == "denied"
    assert "outside" in (decision.reason or "")


def test_absolute_path_outside_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    gateway = write_config(tmp_path, root)
    decision = gateway.check_permission("read", "/etc/passwd")
    assert decision.state == "denied"


def test_symlink_to_etc_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "escape").symlink_to("/etc", target_is_directory=True)
    gateway = write_config(tmp_path, root)
    decision = gateway.check_permission("read", str(root / "escape" / "passwd"))
    assert decision.state == "denied"


def test_allow_executes_only_after_single_check(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    target = root / "safe.txt"
    target.write_text("safe", encoding="utf-8")
    gateway = write_config(tmp_path, root)
    decision, result = gateway.execute("read", str(target), lambda path: path.read_text(encoding="utf-8"))
    assert decision.state == "allowed"
    assert result == "safe"


def test_ask_queues_then_approved_confirmation_allows_exact_request_once(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    target = root / "safe.txt"
    gateway = write_config(tmp_path, root)
    called = False

    def operation(_: Path) -> None:
        nonlocal called
        called = True

    pending, _ = gateway.execute("modify", str(target), operation)
    assert pending.state == "pending_confirmation"
    assert called is False
    assert pending.confirmation_id is not None
    assert gateway.confirmations.decide(pending.confirmation_id, approve=True) is not None
    allowed, _ = gateway.execute("modify", str(target), operation, pending.confirmation_id)
    assert allowed.state == "allowed"
    assert called is True
    replay, _ = gateway.execute("modify", str(target), operation, pending.confirmation_id)
    assert replay.state == "pending_confirmation"


def test_denied_path_never_executes(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    gateway = write_config(tmp_path, root)
    decision, result = gateway.execute(
        "read", "/etc/passwd", lambda _: (_ for _ in ()).throw(AssertionError("must not execute"))
    )
    assert decision.state == "denied"
    assert result is None
