# meld — NeMo Switchyard × Hermes Agent

Live [NeMo Switchyard](https://github.com/NVIDIA-NeMo/Switchyard) routing
visibility inside [Hermes Agent](https://github.com/NousResearch/hermes-agent):
a footer with request/token/cost totals and the served model, `/nvusage` and
`/nvfooter` commands, a switchyard section in the native `/usage`, and the
model name in NVIDIA green while your session routes through Switchyard.

## Quick start

```bash
hermes skills install PicoNVIDIA/meld/nemo-switchyard --category mlops   # the self-setup skill
# then tell your agent: "set up the switchyard integration"
```

Or install directly:

```bash
hermes plugins install PicoNVIDIA/meld --enable
# copy nvhermes.launcher to ~/.local/bin/nvhermes && chmod +x it
OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1 OPENROUTER_API_KEY=dummy \
  nvhermes --provider openrouter -m <route-id>
```

(To route every session by default, configure your model endpoint through
Hermes's own model settings — your call, nothing here changes it for you.)

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
| `plugin.yaml`, `__init__.py` | Hermes plugin: `/nvusage`, `/nvfooter`, bundled skill |
| `switchyard_client.py` | stdlib client: fingerprinting, stats/decisions, shared renderer |
| `nvhermes_cli.py`, `nvhermes_main.py` | `SwitchyardCLI` wrapper (footer, green model, `/usage` section) |
| `nvhermes.launcher` | launcher template for `~/.local/bin/nvhermes` |
| `scripts/doctor.sh` | PASS/FAIL install & router checks (exit 0 = healthy) |
| `nemo-switchyard/SKILL.md` | self-setup skill: agents follow it to install and verify |

## Health & updates

```bash
scripts/doctor.sh          # or /nvusage status inside a session
hermes plugins update      # pull the latest plugin
hermes skills update       # pull the latest skill
```

Notes: the footer needs `nvhermes` (Hermes plugins can't modify the status
bar); plain `hermes` still gets `/nvusage`. Router stats are in-memory —
they reset with the router. Streaming responses carry no token usage.

# Changelog

- 0.1.0 — initial release: footer (row/bar/min/off), /nvusage, /nvfooter, self-setup skill
