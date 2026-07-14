# meld — NeMo Switchyard × Hermes Agent

Live [NeMo Switchyard](https://github.com/NVIDIA-NeMo/Switchyard) routing
visibility inside [Hermes Agent](https://github.com/NousResearch/hermes-agent) —
in the stock `hermes` command, no wrapper needed: a live footer with
request/token/cost totals and the served model, the `/switchyard` hub, a
switchyard section in the native `/usage`, and the model name in NVIDIA green
while your session routes through Switchyard. Unrouted sessions look
completely stock.

## Quick start

```bash
hermes skills install PicoNVIDIA/meld/nemo-switchyard --category mlops   # the self-setup skill
# then tell your agent: "set up the switchyard integration"
```

Or install directly, then let `/switchyard` do the rest from inside a session:

```bash
hermes plugins install PicoNVIDIA/meld --enable
hermes
```

```
/switchyard init        # build a router config — weak=nemotron ultra, strong=opus 4.8
/switchyard start       # run a local router with it (needs $NVIDIA_API_KEY exported)
/switchyard connect     # register it as a hermes provider → shows in /model
```

then relaunch routed: `hermes --provider switchyard -m switchyard`, or just
pick `switchyard` in `/model` once (Hermes persists it) — one model named
**switchyard**, the router picks the tier per request. Pin a specific
upstream anytime by choosing it from the catalog in `/model`;
`/switchyard disconnect` undoes the provider entry.
(Per-session env alternative, no provider entry:
`OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1 OPENROUTER_API_KEY=dummy
hermes --provider openrouter -m switchyard`.)

## The /switchyard hub

```
/switchyard                control panel: router, managed process, footer, routes, session totals
/switchyard init [k=v]     config builder (strong= weak= classifier= base_url= key_env= port= …)
/switchyard start|stop     manage a local router process
/switchyard connect [url]  add the provider entry (marker-bounded; disconnect removes it)
/switchyard routes|use     list routes / switch this session
/switchyard footer [m]     cycle or set footer style
/switchyard usage|status   usage report / PASS-FAIL health checks
```

Any agent that can run shell commands can perform the setup — point it at
[`nemo-switchyard/SKILL.md`](nemo-switchyard/SKILL.md) (agentskills.io format).

## Footer styles

Switch live with `/nvfooter row|bar|min|off` (persisted; `row` is default):

```
row  ⏚ switchyard │ llm-classifier │ 42 req │ 128.4K tok │ $0.43 │ fast 30 · smart 12 │ → kimi-k2.6
     ⚕ llm-classifier │ 17.9K/272K │ [█░░░░░░░░░] 7% │ 5h 23m │ ⏲ 6s │ ✓ 5h 23m

bar  ⚕ llm-classifier→kimi-k2.6 │ 17.9K/272K │ [█░░░░░░░░░] 7% │ ⏚ 42req $0.43 │ ⏲ 6s │ ✓ 5h 23m

min  ⚕ llm-classifier │ 17.9K/272K │ [█░░░░░░░░░] 7% │ 5h 23m │ ⏲ 6s │ ✓ 5h 23m │ ⏚ $0.43
```

## What's in the box

| Path | Purpose |
|---|---|
| `plugin.yaml`, `__init__.py` | Hermes plugin: `/switchyard` hub + aliases, bundled skill, footer graft |
| `switchyard_client.py` | stdlib client: fingerprinting, stats/decisions, shared renderer |
| `sw_config.py` | config builder + router lifecycle (also a shell CLI for agents) |
| `nvhermes_cli.py`, `nvhermes_main.py`, `nvhermes.launcher` | footer implementation + optional isolated wrapper |
| `scripts/doctor.sh` | PASS/FAIL install & router checks (exit 0 = healthy) |
| `nemo-switchyard/SKILL.md` | self-setup skill: agents follow it to install and verify |

## Health & updates

```bash
scripts/doctor.sh          # or /nvusage status inside a session
hermes plugins update      # pull the latest plugin
hermes skills update       # pull the latest skill
```

Notes: the footer lives in plain `hermes` — the plugin grafts it onto the
CLI at load and it stays dormant unless the session routes through
Switchyard (the optional `nvhermes` wrapper remains for isolated installs).
Router stats are in-memory — they reset with the router. Streaming
responses carry no token usage.

# Changelog

- 0.1.0 — initial release: footer (row/bar/min/off), /nvusage, /nvfooter, self-setup skill
- 0.2.0 — /switchyard hub: control panel, config builder (init), router start/stop, provider connect (routes in /model picker), route switching
- 0.2.1 — agent-driven setup: sw_config.py shell CLI (init/start/stop/connect/disconnect/status), interview-style SKILL.md, key fallback to ~/.hermes/.env for env-scrubbed agent shells
- 0.3.0 — one model ("switchyard") instead of auto/strong/weak; footer grafted into plain hermes at plugin load (nvhermes wrapper now optional)
