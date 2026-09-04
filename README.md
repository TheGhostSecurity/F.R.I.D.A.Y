# F.R.I.D.A.Y. Gateway — Phases 1–2

The FastAPI gateway is the filesystem trust boundary. The model has no filesystem access: the agent sends its proposed tool calls to the gateway's HTTP API, and concrete tools execute only through `Gateway.execute()` and its `check_permission(action, resource)` call.

## Permission configuration

`config/permissions.yaml` defines the only filesystem roots the gateway can address and the decision for each action. Valid decisions are `allow`, `ask`, and `deny`.

The gateway expands `~` and resolves symlinks and `..` before comparing a request against the resolved allowed roots. Relative paths are interpreted under the first allowed root, never under the server's working directory. A path outside every root is always denied, irrespective of the matrix.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/uvicorn friday_gateway.app:app --host 127.0.0.1 --port 8000
```

In another terminal, use the Phase 1 CLI:

```bash
.venv/bin/friday config
.venv/bin/friday pending
.venv/bin/friday approve <id>
.venv/bin/friday deny <id>
```

`pending`, `approve`, and `deny` talk to the running gateway at `http://127.0.0.1:8000`; override it with `FRIDAY_GATEWAY_URL`. The confirmation queue is deliberately in-memory in this MVP phase, so restarting the service clears pending entries.

## Phase 2 tools and agent loop

The gateway exposes exactly these Ollama tool schemas at `GET /tools/schema`:

- `search_files(query, root=None)` — literal ripgrep content and filename search, ranked by match count then mtime.
- `read_file(path)` — UTF-8 file reads, with a 1 MB limit.
- `write_file(path, content)` — uses `create` for new targets and `modify` for existing targets.
- `list_recent(root=None, hours=24)` — files changed in the requested window.

Each calls the gateway authorization wrapper before its filesystem operation. A write subject to `ask` returns `pending_confirmation`; approving the ID authorizes exactly one retried action/resource pair.

Ripgrep is bundled locally at `.tools/ripgrep/` during this setup, so no global package install is required. You may instead set `FRIDAY_RG=/path/to/rg`.

The agent loop defaults to `llama3.1:8b-instruct`, whose tool-call support is generally suitable for this simple loop. Start Ollama separately, pull that model, keep the gateway running, then run:

```bash
# In a terminal that has Ollama installed and available to this user:
ollama serve
ollama pull llama3.1:8b-instruct

# In another terminal, from this project:
friday ask "what am I working on?"
```

Environment variables: `FRIDAY_MODEL` (model name), `OLLAMA_HOST` (default `http://127.0.0.1:11434`), and `FRIDAY_GATEWAY_URL` (default `http://127.0.0.1:8000`). The eight-round tool-call cap prevents a malfunctioning model from looping forever.

## CLI

After the editable install in the setup instructions, these commands are available:

```bash
friday ask "what am I working on?"
friday pending
friday approve <id>
friday deny <id>
friday config
```

`ask` starts the local agent loop; it never obtains direct filesystem access. `pending`, `approve`, and `deny` communicate with the gateway process, so leave that service running in a separate terminal.

If `llama3.1:8b-instruct` produces malformed calls or fails to issue calls for straightforward requests, try `qwen2.5:7b-instruct` or a newer tool-capable model in your local Ollama library before widening any gateway permissions. The authorization boundary remains the same regardless of model reliability.

## Manual permission-boundary checks

With the server running, these must all return `"state":"denied"`:

```bash
curl -s -X POST http://127.0.0.1:8000/permission/check -H 'content-type: application/json' -d '{"action":"read","resource":"/etc/passwd"}'
curl -s -X POST http://127.0.0.1:8000/permission/check -H 'content-type: application/json' -d '{"action":"read","resource":"../../etc/passwd"}'
ln -s /etc ~/Projects/friday-escape-test
curl -s -X POST http://127.0.0.1:8000/permission/check -H 'content-type: application/json' -d '{"action":"read","resource":"~/Projects/friday-escape-test/passwd"}'
rm ~/Projects/friday-escape-test
```

To observe `ask`, submit a modification check against a file within an allowed root, then list and approve it:

```bash
curl -s -X POST http://127.0.0.1:8000/permission/check -H 'content-type: application/json' -d '{"action":"modify","resource":"~/Projects/example.txt"}'
.venv/bin/friday pending
.venv/bin/friday approve <id>
```

Approval is bound to one exact resolved action/resource pair and is consumed on use. Phase 2 will wire this mandatory gateway executor to concrete file tools.

## Tests

```bash
.venv/bin/pytest -q
```

The tests cover `../../` traversal, absolute paths outside the root, a symlink to `/etc`, pending approval behavior, one-time approval use, and the invariant that denied requests do not execute their callback.
