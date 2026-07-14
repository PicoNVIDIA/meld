---
name: nemo-switchyard
description: "Set up and use the NeMo Switchyard integration for Hermes Agent: install the plugin and nvhermes launcher, then read live routing usage via the footer, /nvusage, and /usage."
version: 0.2.0
author: PicoNVIDIA
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [nvidia, switchyard, routing, mlops, usage]
---

# NeMo Switchyard integration for Hermes

[NeMo Switchyard](https://github.com/NVIDIA-NeMo/Switchyard) is an LLM
router/proxy: Hermes points its OpenAI-compatible `base_url` at it, and
Switchyard routes each request to a model tier. This integration makes that
routing visible inside Hermes:

- a live **footer** (three styles) with request/token/cost totals and the
  last served model, with the model name in NVIDIA green while routed
- the **/switchyard hub** — control panel, config builder (`init`), local
  router lifecycle (`start`/`stop`), provider registration (`connect`), route
  listing/switching (`routes`/`use`), footer toggles, usage, health checks
- **/model integration** — with the provider connected, routes appear in the
  native /model picker and `/model <route>` switches in place
- **/nvusage** and **/nvfooter** remain as aliases
- a **switchyard section appended to the native /usage** (under `nvhermes`)

## When to use

- The user asks to set up / install the Switchyard integration for Hermes.
- The user asks how to see Switchyard usage, cost, or routing decisions.

## Setup procedure (for the agent)

All steps are idempotent — re-running them is safe. `HERMES_HOME` defaults to
`~/.hermes`; respect it if set.

1. **Install and enable the plugin** (this also brings the wrapper code):

   ```
   hermes plugins install PicoNVIDIA/meld --enable
   ```

   Fallback without git access: copy this skill's source repository into
   `$HERMES_HOME/plugins/nemo-switchyard/`, then run
   `hermes plugins enable nemo-switchyard` (Hermes's own enable command —
   do not hand-edit configuration files).

2. **Install the `nvhermes` launcher.** Find the installed plugin directory
   (it contains `nvhermes_main.py`; check `hermes plugins list` or glob
   `$HERMES_HOME/plugins/*/nvhermes_main.py`), then copy
   `<plugin-dir>/nvhermes.launcher` to `~/.local/bin/nvhermes` and make it
   executable with `chmod +x ~/.local/bin/nvhermes`. Confirm `~/.local/bin`
   is on the user's PATH.

3. **Verify.** Run `<plugin-dir>/scripts/doctor.sh` — every required line
   must be PASS (router lines are skipped when no router is running).
   In a Hermes session, `/nvusage status` shows the same checklist.

4. **Report to the user**, briefly: what was installed; launch with
   `nvhermes` (plain `hermes` is untouched); how to point a session at a
   router (see "Point Hermes at Switchyard" below); switch footer styles
   with `/nvfooter row|bar|min|off`; see usage with `/nvusage` or `/usage`.

## Using it

**The easy path — all inside a session:**

```
/switchyard init          # writes ~/.hermes/switchyard/routes.yaml
                          # defaults: weak=nemotron ultra, strong=opus 4.8, nano classifier
/switchyard start         # runs a local router with it ($NVIDIA_API_KEY must be exported)
/switchyard connect       # registers provider "switchyard" so /model lists the routes
```

Then relaunch routed: `nvhermes --provider switchyard -m auto`. Routes show
in the `/model` picker under **Switchyard**; `/model strong`, `/model weak`,
or `/switchyard use <route>` switch in place. `/switchyard disconnect`
removes the provider entry again (it is marker-bounded — nothing else in the
user's configuration is touched, and both commands only run when the user
invokes them). `init` accepts `key=value` overrides: `strong=`, `weak=`,
`classifier=`, `base_url=`, `key_env=`, `port=`, `profile=`,
`strong_format=`, `weak_format=`, `min_confidence=`. If `start` cannot find
the switchyard executable, set it once with `/switchyard bin <path>` or
export `SWITCHYARD_BIN`.

**Per-session env alternative** (no provider entry; the dummy key is fine —
the router holds the real keys):

```
OPENROUTER_BASE_URL=http://127.0.0.1:<port>/v1 OPENROUTER_API_KEY=dummy \
  nvhermes --provider openrouter -m <route-id>
```

Note: setting only the env base_url without `--provider openrouter` is not
enough — Hermes keeps its configured provider and traffic bypasses the
router. While the session's endpoint fingerprints as Switchyard, the model
name in the status bar renders NVIDIA green and the footer is live.

**Footer styles** (`/nvfooter <mode>`, persisted across sessions;
`SWITCHYARD_FOOTER` env overrides):

```
row  ⏚ switchyard │ llm-classifier │ 42 req │ 128.4K tok │ $0.43 │ fast 30 · smart 12 │ → kimi-k2.6
     ⚕ llm-classifier │ 17.9K/272K │ [█░░░░░░░░░] 7% │ 5h 23m │ ⏲ 6s │ ✓ 5h 23m
bar  ⚕ llm-classifier→kimi-k2.6 │ 17.9K/272K │ [█░░░░░░░░░] 7% │ ⏚ 42req $0.43 │ ⏲ 6s │ ✓ 5h 23m
min  ⚕ llm-classifier │ 17.9K/272K │ [█░░░░░░░░░] 7% │ 5h 23m │ ⏲ 6s │ ✓ 5h 23m │ ⏚ $0.43
off  (stock bar; model name stays green while routed)
```

**Commands.** `/switchyard` — control panel (router, managed process,
footer, routes, session totals); `/switchyard usage` (alias `/nvusage`) —
aggregate + per-model usage table and recent routing decisions;
`/switchyard status` — PASS/FAIL health checklist; `/switchyard reset` —
reset the router's stats; `/switchyard footer` — cycle footer styles
(alias `/nvfooter`). `/usage` — the native Hermes usage report gains a
switchyard section under `nvhermes`.

**Raw endpoints** (for scripts): `GET /health` → `{"status":"ok"}`;
`GET /v1/models` → route ids, entries have `"owned_by": "switchyard"`;
`GET /v1/routing/stats` → totals + per-model
`{tier, calls, *_tokens, estimated_cost_usd}`;
`GET /v1/routing/decisions` → per-request
`{tier, source, confidence, outcome, served_model, latency_ms, usage}`.

## Caveats & troubleshooting

- Stats are **in-memory and process-local** to the router — they reset when
  it restarts; persist them yourself if you need history.
- **Streaming responses carry no token usage** at the router; counters and
  cost undercount streamed traffic.
- `/v1/routing/decisions` exists only under a **deterministic routing
  profile** on routers that include per-decision telemetry; everything else
  degrades gracefully without it.
- **No green model name?** The session's endpoint must itself be the router
  (`/nvusage status` shows the fingerprint check) — use the
  `OPENROUTER_BASE_URL` + `--provider openrouter` launch shown above.
  `SWITCHYARD_URL` enables inspection only, not routing.
- **Footer missing?** It needs `nvhermes` (plain `hermes` can't touch the
  status bar) and `/nvfooter status` should not say `off`.
- **Port conflicts:** pick a free port for test routers; check with
  `lsof -nP -iTCP:<port> -sTCP:LISTEN`.
