# meld — NeMo Switchyard × Hermes Agent

> **Agents:** installing this for a user? Follow [AGENTS.md](AGENTS.md) —
> finish the setup in one command, don't stop at the install.

Live [NeMo Switchyard](https://github.com/NVIDIA-NeMo/Switchyard) routing
visibility inside [Hermes Agent](https://github.com/NousResearch/hermes-agent) —
in the stock `hermes` command, no wrapper needed: a live footer with
request/token/cost totals and the served model, the `/switchyard` hub, a
switchyard section in the native `/usage`, and the model name in NVIDIA green.
The whole UX appears exactly while your `/model` is a switchyard route — pin
a catalog model or switch providers and the TUI is completely stock again.

## Quick start

```bash
hermes skills install PicoNVIDIA/meld/nemo-switchyard --category mlops   # the self-setup skill
# then tell your agent: "set up the switchyard integration"
```

Or install directly — first run is one Enter:

```bash
hermes plugins install PicoNVIDIA/meld --enable
hermes                  # → "/switchyard" → Enter on the Quick setup row
```

Quick setup does everything (writes the default config, probes your keys,
starts the router, registers the provider) with live progress in the panel.
Prefer choosing your own tiers first? `/switchyard build` walks you through
searchable pickers; `start`/`connect` remain as individual steps.

`/switchyard build` walks you through Hermes's native model picker twice —
strong tier, then weak — listing only connected providers Switchyard can call
directly (API-key based; OAuth providers are skipped with a note). Each pick
is translated into a Switchyard target automatically: endpoint URL, key env
var, and wire format come from your Hermes provider config, so mixing (say)
an NVIDIA NIM strong tier with an OpenRouter weak tier just works.

then relaunch routed: `hermes --provider switchyard -m switchyard`, or just
pick `switchyard` in `/model` once (Hermes persists it) — one model named
**switchyard**, the router picks the tier per request. Pin a specific
upstream anytime by choosing it from the catalog in `/model`;
`/switchyard disconnect` undoes the provider entry.
(Per-session env alternative, no provider entry:
`OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1 OPENROUTER_API_KEY=dummy
hermes --provider openrouter -m switchyard`.)

## The /switchyard hub

`/switchyard` opens an **interactive panel** — ↑/↓ to move, Enter to act,
←/→ to cycle the footer style, Esc to close: toggle the router on/off,
connect/disconnect the provider, re-pick the strong/weak tiers (searchable),
run the key preflight, route the session. In the model pickers, **just type
to search** (🔎 shows in the title, Backspace edits) — 100+ models filter to
a handful in a few keystrokes.

```
/switchyard                interactive panel (text version: /switchyard panel)
/switchyard build [k=v]    interactive tier picker over your connected models
/switchyard init [k=v]     non-interactive config (strong= weak= classifier= base_url= key_env= port= …)
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
- 0.3.1 — UX gated on the selected /model being a switchyard route, re-checked live: pin a catalog model or switch providers and the TUI is stock again; /model switchyard brings it back
- 0.4.0 — /switchyard build: interactive tier picker over your connected Hermes providers (native /model picker UI); per-tier endpoints/keys/formats in the generated config; multi-key router start
- 0.5.0 — interactive everything: /switchyard opens an arrow-key panel (footer/router/provider toggles, tier pickers, preflight); type-to-search in model pickers; single-tier edits keep the rest of the config
- 0.6.0 — first-run in one Enter: Quick setup row in the panel (config → keys → router → provider with live progress), sw_config.py setup one-shot for agents, one-time install hint
