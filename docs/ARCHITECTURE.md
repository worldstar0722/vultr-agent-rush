# Architecture

```
Browser (static HTML/JS)  --HTTP-->  Caddy  -->  FastAPI (app/main.py)
                                                   |-- RunManager: 1 thread per run
                                                   |-- Agent loop: plan -> act -> verify
                                                   |-- EventStore (in memory) <-- SSE stream to browser
                                                   |-- LLM client --> Vultr Serverless Inference
                                                   `-- Sandbox runner --> docker run (throwaway container)
```

## Code map

| Path | What it does |
|---|---|
| `app/main.py` | FastAPI app factory and all HTTP endpoints |
| `app/config.py` | All settings from env vars (+ product name/tagline placeholder) |
| `app/llm.py` | `MockLLM` and `OpenAICompatLLM` (same interface: `plan`, `verify`, `models`) |
| `app/events.py` | Event types and the `EventStore` interface (in-memory implementation) |
| `app/agent/loop.py` | The plan -> act -> verify loop with limits |
| `app/agent/tools.py` | Tool registry + 3 demo tools to replace |
| `app/agent/approvals.py` | Pause/resume gate for human approval |
| `app/sandbox/runner.py` | Docker sandbox and mock sandbox |
| `app/static/` | The one-page UI |

## HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /api/config` | Branding + active modes (used by the UI) |
| `GET /api/models` | Proxies the provider's model list |
| `POST /api/runs` `{task}` | Start a run, returns `{id}` |
| `GET /api/runs/{id}` | Run status: `running`, `waiting_approval`, `done`, `failed` |
| `GET /api/runs/{id}/events` | SSE: replays the log then streams; final `event: end` |
| `POST /api/runs/{id}/approve` `{approved}` | Resolve a pending approval (409 if none) |

## Event types

`plan`, `tool_call`, `tool_result`, `verify`, `approval_requested`, `approval_granted`, `approval_denied`, `blocked`, `error`, `done`. Each has `id` (per-run sequence), `run_id`, `type`, `data`, `ts`.

## Agent loop rules

- `MAX_STEPS` caps total tool executions per run, retries included -> run fails with an `error`.
- Each planned step: 1 attempt + up to `MAX_RETRIES` (3) retries when `verify` says not ok; then the run fails.
- `requires_approval` tools: status becomes `waiting_approval`, the thread blocks until `POST .../approve` or `APPROVAL_TIMEOUT_SECONDS` (then auto-reject). Asked before every attempt. Reject = step skipped, run continues.
- A tool result with `blocked` produces a `blocked` event; being contained counts as success and is not retried.

## Sandbox (Track 1)

Per run: `docker run -i --network none --read-only --tmpfs /tmp --user 65534 --cpus --memory --pids-limit --cap-drop ALL --security-opt no-new-privileges`, wall-clock timeout, container force-removed afterwards. The code is piped over stdin, so **no host directory is mounted at all**. Blocked reasons come from: timeout, exit 137 + `OOMKilled`, and known error strings for network / read-only-fs attempts (heuristic: see `_NETWORK_HINTS`).

Caveats to be honest about in the demo/slides:
- When the app itself runs in a container, starting sandboxes needs the host Docker socket, which is root-equivalent on the VM. Use a disposable VM. A stronger design would run sandboxes through a separate unprivileged service or gVisor/Firecracker (not done here).
- `SANDBOX_ENABLED=false` (default) or no reachable Docker -> `MockSandbox`, which executes nothing.

## Swapping things

- **Persistence**: implement the 5 methods of `EventStore` (e.g. SQLite) and pass `store=` to `create_app`.
- **Tools**: edit `build_default_registry` in `app/agent/tools.py`.
- **Multiple workers**: the in-memory store and approval gate are per-process; run a single uvicorn worker (the default).
