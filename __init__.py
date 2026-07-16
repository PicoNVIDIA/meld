"""NeMo Switchyard integration for Hermes Agent.

Registers the /router command hub (/switchyard, /nvusage, /nvfooter aliases)
and bundles the nemo-switchyard skill. The TUI footer itself lives in
nvhermes_cli.py and is grafted onto HermesCLI at load, so the stock `hermes`
command renders it (dormant unless the session routes through Switchyard).
"""
from __future__ import annotations

import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import sw_config
import sw_settings
import switchyard_client as swc

_NOT_FOUND_HINT = (
    "no router detected.\n"
    "  · build a config:  /router init          (ultra=weak, opus=strong defaults)\n"
    "  · start a router:  /router start\n"
    "  · connect + relaunch:  /router connect, then hermes --provider router -m router\n"
    "  · or set SWITCHYARD_URL for inspection without routing\n"
    "  · checks: /router status"
)

_HELP = """\
/router                control panel (this overview)
/router build [k=v]    interactive builder — pick strong/weak tiers from your connected models
/router init [k=v]     non-interactive config with defaults
/router start|stop     run/stop a local router with that config
/router connect [url]  register the router as a hermes provider (shows in /model picker)
/router disconnect     remove that provider entry again
/router routes         list the configured routes
/router use <route>    switch this session to a route (also: /model <route>)
/router footer [m]     toggle footer style (row → bar → min → off), or set one
/router usage          usage & routing decisions   (alias: /nvusage)
/router reset          reset the router's stats
/router status         PASS/FAIL health checklist
/router bin <path>     remember where the router executable lives
init keys: strong= weak= classifier= base_url= key_env= port= profile= strong_format= weak_format= min_confidence="""


def register(ctx):
    g, d, b, r = swc.GREEN, swc.DIM, swc.BOLD, swc.RST

    # Graft the footer onto HermesCLI itself so the stock `hermes` command
    # renders it (dormant unless the session routes through Switchyard).
    try:
        import nvhermes_cli
        nvhermes_cli.graft()
    except Exception:
        pass

    def _cli_ref():
        try:
            return ctx._manager._cli_ref
        except Exception:
            return None

    def _session_base_url():
        ref = _cli_ref()
        if ref is None:
            return None
        url = getattr(ref, "base_url", None)
        if url:
            return url
        return getattr(getattr(ref, "agent", None), "base_url", None)

    def _find_root():
        return swc.resolve_url(_session_base_url())

    def _load_settings():
        try:
            import json
            data = json.loads((_DIR / "settings.json").read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_setting(key, value):
        import json
        path = _DIR / "settings.json"
        data = _load_settings()
        data[key] = value
        path.write_text(json.dumps(data, indent=2))

    # ── subcommand handlers ────────────────────────────────────────────────
    def _panel():
        ref = _cli_ref()
        root = _find_root()
        routed = ref is not None and getattr(ref, "_sw_active", False)
        lines = [f"{g}{b}⏚ router{r}"]
        lines.append(f"  endpoint  {root or 'not detected'}"
                     + (f"  {g}● routed{r}" if routed else (f"  {d}(inspection only — session not routed){r}" if root else "")))
        state = sw_config.router_state()
        if state:
            flag = f"{g}running{r}" if state.get("running") else "stopped"
            lines.append(f"  managed   {flag}  {d}pid {state.get('pid')} · port {state.get('port')} · {state.get('config')}{r}")
        lines.append(f"  footer    {sw_settings.load_mode()}  {d}(/router footer to cycle){r}")
        if ref is not None:
            lines.append(f"  route     {getattr(ref, 'model', None) or '-'}")
        if root:
            rts, default = swc.routes(root)
            if rts:
                names = " · ".join(
                    ("%s%s%s" % (b, rt["id"], r)) + (f" {d}(default){r}" if rt["id"] == default else "")
                    for rt in rts)
                lines.append(f"  routes    {names}")
            st = swc.stats(root)
            if st:
                lines.append(f"  session   {st.get('total_requests', 0)} req · "
                             f"{swc.fmt_tokens((st.get('total_tokens') or {}).get('total'))} tok · "
                             f"{swc.fmt_cost(swc.total_cost(st))}")
        lines.append(f"{d}{_HELP}{r}")
        return "\n".join(lines)

    def _status_report():
        lines = [f"{g}{b}── router status ──{r}"]

        def check(ok, label, optional=False):
            mark = f"{g}PASS{r}" if ok else (f"{d}  — {r}" if optional else "FAIL")
            lines.append(f"  {mark}  {label}")

        ref = _cli_ref()
        check(True, "plugin loaded (/router registered)")
        session_url = _session_base_url()
        root = _find_root()
        routed = (ref is not None and getattr(ref, "_sw_active", False)) or (
            bool(session_url) and swc.detect(session_url) is not None
        )
        check(root is not None, f"router reachable ({root or 'none found'})")
        if root:
            check(swc.health_ok(root), f"health ok at {root}/health")
            check(swc.stats(root) is not None, "stats endpoint (/v1/routing/stats)")
            check(swc.decisions(root) is not None,
                  "decisions endpoint (/v1/routing/decisions — needs deterministic profile)",
                  optional=True)
        check(routed, "router model selected — UX active (green model name, footer)", optional=True)
        check(ref is not None and hasattr(ref, "_sw_switch_route"),
              "footer grafted into this session", optional=True)
        if sw_config.CONFIG_PATH.exists():
            try:
                for res in sw_config.preflight():
                    label = f"upstream key ${res['key_env']} at {res['base_url']}"
                    if res["status"] == 200:
                        check(True, label)
                    elif res["status"] in (401, 403, "missing"):
                        check(False, f"{label} (HTTP {res['status']})" if res["status"] != "missing"
                              else f"{label} — no value set")
                    else:
                        check(False, f"{label} — unreachable", optional=True)
            except Exception:
                pass
        lines.append(f"  {d}footer mode: {sw_settings.load_mode()}{r}")
        return "\n".join(lines)

    def _usage():
        root = _find_root()
        if root is None:
            return _NOT_FOUND_HINT
        return swc.render_usage(root, swc.stats(root), swc.decisions(root))

    def _reset():
        root = _find_root()
        if root is None:
            return _NOT_FOUND_HINT
        if swc.reset(root) is not None:
            return f"router stats reset at {root}"
        return f"reset failed — POST {root}/v1/stats/reset not available"

    def _routes():
        root = _find_root()
        if root is None:
            return _NOT_FOUND_HINT
        rts, default = swc.routes(root)
        if not rts:
            return f"no configured routes advertised at {root}/v1/models"
        ref = _cli_ref()
        current = getattr(ref, "model", None) if ref else None
        lines = [f"{g}{b}── routes at {root} ──{r}"]
        for rt in rts:
            mark = f"{g}▶{r}" if rt["id"] == current else " "
            suffix = f" {d}(default){r}" if rt["id"] == default else ""
            ctxw = swc.fmt_tokens(rt.get("context_window")) if rt.get("context_window") else "?"
            lines.append(f"  {mark} {b}{rt['id']:<20}{r} {d}{rt['profile']:<14} ctx {ctxw}{r}{suffix}")
        lines.append(f"{d}switch with /router use <route> (or /model <route>){r}")
        return "\n".join(lines)

    def _use(route):
        if not route:
            return "usage: /router use <route> — see /router routes"
        ref = _cli_ref()
        if ref is None or not hasattr(ref, "_sw_switch_route"):
            return "route switching needs a session routed through the router"
        return ref._sw_switch_route(route)

    def _footer(mode):
        current = sw_settings.load_mode()
        if not mode:
            order = list(sw_settings.MODES)
            mode = order[(order.index(current) + 1) % len(order)]
        if mode == "status":
            return f"footer mode: {current}  (styles: row · bar · min · off)"
        if mode not in sw_settings.MODES:
            return f"unknown mode {mode!r} — pick one of: row, bar, min, off (or 'status')"
        sw_settings.save_mode(mode)
        ref = _cli_ref()
        applied = False
        if ref is not None:
            ref._sw_footer_mode = mode
            try:
                ref._invalidate()
            except Exception:
                pass
            applied = True
        note = "" if applied else " (persisted — applies to the next session)"
        return f"footer → {mode}{note}"

    def _init(raw):
        opts, unknown = sw_config.parse_kv(raw)
        if unknown:
            return ("unrecognized: " + " ".join(unknown)
                    + "\nknown keys: " + " ".join(sorted(sw_config.KNOWN_KEYS)) + " (key=value)")
        path = sw_config.write_config(opts)
        _save_setting("router_port", int(opts["port"]))
        return (
            f"{g}{b}✓ wrote {path}{r}\n"
            f"  one model: {b}router{r} {d}— {opts['classifier'].rsplit('/', 1)[-1]} picks between"
            f" {opts['strong'].rsplit('/', 1)[-1]} (strong) and {opts['weak'].rsplit('/', 1)[-1]} (weak){r}\n"
            f"  key: read from ${opts['key_env']} at router start (never stored)\n"
            f"  next: {b}/router start{r} → {b}/router connect{r} → relaunch with"
            f" {b}hermes --provider router -m router{r}"
        )

    def _connect(raw):
        url = raw.strip()
        if not url:
            state = sw_config.router_state()
            if state and state.get("running"):
                url = f"http://127.0.0.1:{state['port']}/v1"
            else:
                root = _find_root()
                url = (root + "/v1") if root else ""
        if not url:
            return "no router url given and none detected — /router connect <url>"
        root = swc.detect(url)
        if root is None:
            return f"{url} does not fingerprint as a router (is it up yet? ~15s to bind)"
        rts, _default = swc.routes(root)
        ids = [rt["id"] for rt in rts]
        ok, msg = sw_config.connect_provider(root + "/v1", ids)
        if not ok:
            return msg
        return (
            f"{g}{b}✓ {msg}{r}\n"
            f"  provider {b}router{r} → {root}/v1  {d}routes: {', '.join(ids) or '-'}{r}\n"
            f"  · new sessions: {b}hermes --provider router -m {ids[0] if ids else '<route>'}{r}\n"
            f"  · the /model picker now lists these under {b}Router{r}\n"
            f"  · undo anytime: {b}/router disconnect{r}"
        )

    def _disconnect():
        ok, msg = sw_config.disconnect_provider()
        return (f"{g}✓ {msg}{r}" if ok else msg)

    def _start(raw):
        settings = _load_settings()
        bin_path = sw_config.find_switchyard_bin(settings)
        if not bin_path:
            return ("router executable not found — set it once with "
                    "/router bin <path> (or export SWITCHYARD_BIN)")
        cfg = Path(raw.strip()) if raw.strip() else sw_config.CONFIG_PATH
        if not cfg.exists():
            return f"no config at {cfg} — run /router init first"
        port, key_env = sw_config.DEFAULTS["port"], sw_config.DEFAULTS["key_env"]
        try:
            text = cfg.read_text()
            import re
            m = re.search(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
            if m:
                key_env = m.group(1)
        except Exception:
            pass
        stored_port = settings.get("router_port")
        if stored_port:
            port = str(stored_port)
        ok, msg = sw_config.start_router(bin_path, cfg, port, key_env)
        return (f"{g}{msg}{r}" if ok else msg)

    def _bin(raw):
        p = raw.strip()
        if not p:
            found = sw_config.find_switchyard_bin(_load_settings())
            return f"router bin: {found or 'not set'} — set with /router bin <path>"
        if not Path(p).exists():
            return f"no file at {p}"
        _save_setting("switchyard_bin", p)
        return f"✓ router bin → {p}"

    # ── dispatch ───────────────────────────────────────────────────────────
    def _handle_switchyard(raw_args=""):
        raw = (raw_args or "").strip()
        cmd, _, rest = raw.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        if cmd == "":
            ref = _cli_ref()
            if ref is not None and hasattr(ref, "_sw_open_menu"):
                try:
                    ref._sw_open_menu()
                    return "⏚ ↑/↓ move · Enter select · ←/→ cycle footer · Esc close   (/router panel for text)"
                except Exception:
                    pass
            return _panel()
        if cmd == "panel":
            return _panel()
        if cmd in ("help", "-h", "--help"):
            return _HELP
        if cmd == "status":
            return _status_report()
        if cmd == "usage":
            return _usage()
        if cmd == "reset":
            return _reset()
        if cmd == "routes":
            return _routes()
        if cmd == "use":
            return _use(rest)
        if cmd == "footer":
            return _footer(rest.lower())
        if cmd == "build":
            ref = _cli_ref()
            fn = getattr(ref, "_sw_start_builder", None) if ref is not None else None
            if fn is None:
                return "the interactive builder needs a TUI session with the plugin loaded"
            return fn(rest)
        if cmd == "init":
            return _init(rest)
        if cmd == "connect":
            return _connect(rest)
        if cmd == "disconnect":
            return _disconnect()
        if cmd == "start":
            return _start(rest)
        if cmd == "stop":
            ok, msg = sw_config.stop_router()
            return (f"{g}{msg}{r}" if ok else msg)
        if cmd == "bin":
            return _bin(rest)
        return f"unknown subcommand {cmd!r}\n{_HELP}"

    # ── back-compat aliases ────────────────────────────────────────────────
    def _handle_nvusage(raw_args=""):
        args = (raw_args or "").strip().lower()
        if args == "status":
            return _status_report()
        if args == "reset":
            return _reset()
        if args:
            return "usage: /nvusage [status|reset]"
        return _usage()

    def _handle_nvfooter(raw_args=""):
        mode = (raw_args or "").strip().lower()
        return _footer("status" if mode == "" else mode)

    # One-time first-run hint: fresh install, nothing configured yet.
    try:
        if not sw_config.CONFIG_PATH.exists() and not _load_settings().get("first_run_hint_shown"):
            _save_setting("first_run_hint_shown", True)
            print("⏚ router plugin installed — type /router and press Enter on Quick setup (~30s)")
    except Exception:
        pass

    ctx.register_command(
        "router",
        _handle_switchyard,
        description="Model-router control panel: routes, footer toggles, usage, config builder, start/stop",
        args_hint="[build|init|start|stop|connect|routes|use|footer|usage|status|reset|bin]",
    )
    ctx.register_command(
        "switchyard",
        _handle_switchyard,
        description="Alias of /router",
    )
    ctx.register_command(
        "nvusage",
        _handle_nvusage,
        description="Router usage & routing stats (alias of /router usage)",
    )
    ctx.register_command(
        "nvfooter",
        _handle_nvfooter,
        description="Router footer style: row|bar|min|off (alias of /router footer)",
    )
    try:
        ctx.register_skill(
            "nemo-switchyard",
            _DIR / "nemo-switchyard" / "SKILL.md",
            description="Set up and use the NeMo Switchyard integration for Hermes",
        )
    except Exception:
        pass
