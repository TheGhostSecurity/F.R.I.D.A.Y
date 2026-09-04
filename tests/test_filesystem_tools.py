from pathlib import Path

from fastapi.testclient import TestClient

from friday_gateway.app import create_app
from friday_gateway.config import load_config
from friday_gateway.permissions import Gateway
from friday_gateway.tools import FilesystemTools, TOOL_SCHEMAS


def make_tools(tmp_path: Path, permissions: dict[str, str] | None = None) -> tuple[FilesystemTools, Path]:
    root = tmp_path / "allowed"
    root.mkdir()
    config = tmp_path / "permissions.yaml"
    matrix = permissions or {"read": "allow", "create": "allow", "modify": "ask", "delete": "ask"}
    config.write_text("filesystem:\n  allowed_roots:\n    - " + str(root) + "\n  permissions:\n" + "\n".join(f"    {key}: {value}" for key, value in matrix.items()) + "\n")
    return FilesystemTools(Gateway(load_config(config))), root


def test_search_read_and_recent_are_scoped(tmp_path: Path) -> None:
    tools, root = make_tools(tmp_path)
    note = root / "project-notes.txt"
    note.write_text("Friday gateway architecture", encoding="utf-8")
    assert tools.search_files("gateway")["results"][0]["path"] == str(note)
    assert tools.read_file(str(note))["result"]["content"] == "Friday gateway architecture"
    assert tools.list_recent(hours=1)["results"][0]["path"] == str(note)


def test_search_does_not_follow_symlinks_outside_root(tmp_path: Path) -> None:
    tools, root = make_tools(tmp_path)
    (root / "escape").symlink_to("/etc", target_is_directory=True)
    result = tools.search_files("root")
    assert result["state"] == "allowed"
    assert all(not item["path"].startswith("/etc") for item in result["results"])


def test_write_modification_requires_and_consumes_confirmation(tmp_path: Path) -> None:
    tools, root = make_tools(tmp_path)
    note = root / "note.txt"
    note.write_text("old", encoding="utf-8")
    pending = tools.write_file(str(note), "new")
    assert pending["state"] == "pending_confirmation"
    assert note.read_text() == "old"
    assert tools.gateway.confirmations.decide(pending["confirmation_id"], approve=True)
    written = tools.write_file(str(note), "new", pending["confirmation_id"])
    assert written["state"] == "allowed"
    assert note.read_text() == "new"


def test_write_create_is_allowed_and_escape_is_denied(tmp_path: Path) -> None:
    tools, root = make_tools(tmp_path)
    created = tools.write_file(str(root / "new.txt"), "created")
    assert created["state"] == "allowed"
    assert (root / "new.txt").read_text() == "created"
    assert tools.write_file("/tmp/not-allowed.txt", "no")["state"] == "denied"


def test_tool_schemas_cover_exact_phase_two_tools() -> None:
    assert {item["function"]["name"] for item in TOOL_SCHEMAS} == {"search_files", "read_file", "write_file", "list_recent"}


def test_tool_http_endpoint_executes_via_gateway(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("gateway endpoint", encoding="utf-8")
    config = tmp_path / "permissions.yaml"
    config.write_text("filesystem:\n  allowed_roots:\n    - " + str(root) + "\n  permissions:\n    read: allow\n    create: allow\n    modify: ask\n    delete: ask\n")
    client = TestClient(create_app(config))
    response = client.post("/tools/execute", json={"name": "read_file", "arguments": {"path": str(note)}})
    assert response.status_code == 200
    assert response.json()["result"]["content"] == "gateway endpoint"
    escaped = client.post("/tools/execute", json={"name": "read_file", "arguments": {"path": "/etc/passwd"}})
    assert escaped.json()["state"] == "denied"
