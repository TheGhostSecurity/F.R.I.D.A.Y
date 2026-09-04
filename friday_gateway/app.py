from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import load_config
from .permissions import Gateway
from .tools import FilesystemTools, TOOL_SCHEMAS


class PermissionCheckRequest(BaseModel):
    action: str
    resource: str
    confirmation_id: str | None = None


class ToolExecuteRequest(BaseModel):
    name: str
    arguments: dict = {}


def create_app(config_path: str | Path | None = None) -> FastAPI:
    selected_config = config_path or os.environ.get("FRIDAY_CONFIG", "config/permissions.yaml")
    gateway = Gateway(load_config(selected_config))
    tools = FilesystemTools(gateway)
    app = FastAPI(title="F.R.I.D.A.Y. Gateway", version="0.1.0")
    app.state.gateway = gateway
    app.state.tools = tools

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/permission/check")
    def permission_check(request: PermissionCheckRequest) -> dict[str, str | None]:
        return gateway.check_permission(request.action, request.resource, request.confirmation_id).__dict__

    @app.get("/tools/schema")
    def tool_schema() -> dict[str, list[dict]]:
        return {"tools": TOOL_SCHEMAS}

    @app.post("/tools/execute")
    def execute_tool(request: ToolExecuteRequest) -> dict:
        return tools.execute(request.name, request.arguments)

    @app.get("/confirmations")
    def list_confirmations() -> dict[str, list[dict[str, str]]]:
        return {"pending": gateway.confirmations.list_pending()}

    @app.post("/confirmations/{confirmation_id}/approve")
    def approve(confirmation_id: str) -> dict[str, str]:
        item = gateway.confirmations.decide(confirmation_id, approve=True)
        if item is None:
            raise HTTPException(404, "pending confirmation not found")
        return {"id": item.id, "status": item.status}

    @app.post("/confirmations/{confirmation_id}/deny")
    def deny(confirmation_id: str) -> dict[str, str]:
        item = gateway.confirmations.decide(confirmation_id, approve=False)
        if item is None:
            raise HTTPException(404, "pending confirmation not found")
        return {"id": item.id, "status": item.status}

    return app


app = create_app()
