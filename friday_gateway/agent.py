from __future__ import annotations

import json
import os
import argparse
from typing import Any
from urllib.request import Request, urlopen

from .tools import TOOL_SCHEMAS

SYSTEM_PROMPT = "You are F.R.I.D.A.Y., a local personal assistant. Use tools only when needed. Never claim a filesystem action occurred unless the tool result says state=allowed. If a result is pending_confirmation, explain that the user must approve it."


class OllamaAgent:
    """Model client with no filesystem privileges: it uses gateway HTTP tools only."""

    def __init__(self, gateway_url: str | None = None, ollama_url: str | None = None, model: str | None = None) -> None:
        self.gateway_url = (gateway_url or os.environ.get("FRIDAY_GATEWAY_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.ollama_url = (ollama_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("FRIDAY_MODEL", "llama3.1:8b-instruct")

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read())

    def ask(self, user_query: str) -> str:
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_query}]
        for _ in range(8):
            reply = self._post(f"{self.ollama_url}/api/chat", {"model": self.model, "messages": messages, "tools": TOOL_SCHEMAS, "stream": False})
            message = reply["message"]
            messages.append(message)
            calls = message.get("tool_calls") or []
            if not calls:
                return message.get("content", "")
            for call in calls:
                function = call["function"]
                outcome = self._post(f"{self.gateway_url}/tools/execute", {"name": function["name"], "arguments": function.get("arguments") or {}})
                messages.append({"role": "tool", "tool_name": function["name"], "content": json.dumps(outcome)})
        return "I stopped after the maximum of 8 tool-call rounds."


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 2 F.R.I.D.A.Y. agent loop.")
    parser.add_argument("query")
    args = parser.parse_args()
    print(OllamaAgent().ask(args.query))


if __name__ == "__main__":
    main()
