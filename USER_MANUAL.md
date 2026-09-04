# F.R.I.D.A.Y. User Manual

F.R.I.D.A.Y. is a local personal agent. It asks a local Ollama model to reason about your request, but filesystem access is always mediated by the F.R.I.D.A.Y. Gateway.

## Before you start

From the project directory, install the project into its virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Edit `config/permissions.yaml` before using the agent. Only paths under `filesystem.allowed_roots` can be accessed. The defaults are `~/Projects` and `~/Documents`.

## Start F.R.I.D.A.Y.

Open three terminals.

In terminal 1, start the gateway:

```bash
cd /home/ghostriley23/Desktop/F.R.I.D.A.Y
.venv/bin/uvicorn friday_gateway.app:app --host 127.0.0.1 --port 8000
```

In terminal 2, start Ollama and make sure the selected model is available:

```bash
ollama serve
ollama pull llama3.1:8b-instruct
```

In terminal 3, ask F.R.I.D.A.Y. a question:

```bash
cd /home/ghostriley23/Desktop/F.R.I.D.A.Y
.venv/bin/friday ask "what am I working on?"
```

## Commands

Ask a question:

```bash
.venv/bin/friday ask "find files mentioning the gateway"
```

Show confirmations that need your decision:

```bash
.venv/bin/friday pending
```

Approve or reject a pending operation:

```bash
.venv/bin/friday approve <confirmation-id>
.venv/bin/friday deny <confirmation-id>
```

Show the active permission configuration:

```bash
.venv/bin/friday config
```

## Permissions and confirmations

The gateway applies the following action types to every filesystem tool call:

| Action | Meaning |
| --- | --- |
| `read` | Search, list, or read a file. |
| `create` | Create a new file. |
| `modify` | Change an existing file. |
| `delete` | Delete a file. |

Each action can be set to `allow`, `ask`, or `deny` in `config/permissions.yaml`.

When an action is `ask`, the gateway does not perform it. It returns a confirmation ID instead. Review it with `friday pending`, then approve or deny it. An approval is valid for one exact action and one exact resolved path; it cannot be reused for another file.

The confirmation queue is stored in memory. Restarting the gateway clears pending confirmations.

## Available capabilities

F.R.I.D.A.Y. can currently:

- Search filenames and text inside allowed roots.
- Read UTF-8 text files up to 1 MB.
- Create or modify text files according to the configured permissions.
- List recently changed files.

It cannot currently use calendars, notifications, external APIs, semantic search, or file watching.

## Safety boundary

The gateway resolves `~`, `..`, and symlinks before checking a path. Requests that end up outside an allowed root are denied, including paths such as `/etc/passwd`, `../../etc/passwd`, or a symlink inside an allowed root pointing to `/etc`.

Do not add broad filesystem locations such as `/` to `allowed_roots`.

## Configuration example

```yaml
filesystem:
  allowed_roots:
    - ~/Projects
    - ~/Documents
  permissions:
    read: allow
    create: allow
    modify: ask
    delete: ask
```

Restart the gateway after changing this file.

## Troubleshooting

**`Could not reach Ollama or the gateway`**

Confirm that the gateway is listening on `127.0.0.1:8000` and Ollama on `127.0.0.1:11434`. Start both services before running `friday ask`.

**The model does not use tools**

Confirm the model is installed with `ollama list`. F.R.I.D.A.Y. defaults to `llama3.1:8b-instruct`; set `FRIDAY_MODEL` to use another installed model:

```bash
FRIDAY_MODEL=qwen2.5:7b-instruct .venv/bin/friday ask "list recent files"
```

**A file is denied**

Run `friday config` and verify the file is inside an allowed root after resolving symlinks. A model cannot override this boundary.

**A modification remains pending**

Use `friday pending`, inspect the requested path, and use `friday approve <id>` or `friday deny <id>`.
