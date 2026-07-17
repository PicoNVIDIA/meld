"""Router TUI for Hermes — grafted onto HermesCLI at plugin load.

The plugin calls graft() when Hermes loads it (same process), wrapping a few
HermesCLI methods on the CLASS so the stock `hermes` command gets the footer,
green model name, /usage section, the /router panel, and /model integration.
Every wrapper falls back to stock behavior on any exception, and everything
stays dormant unless the selected /model is a route on a detected router.

State is initialized lazily on first render (_sw_ensure_init): detection and
stats polling run in a daemon thread, never on the render path.

Footer styles (persisted via sw_settings, cycled with /router footer):
row (default) · bar · min · off.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import sw_settings
import switchyard_client as swc

_POLL_SECS = 2.0


def _dw(text):
    """Terminal display width — wide glyphs (CJK, symbols like ⏚⏳●) count 2."""
    import unicodedata
    w = 0
    for ch in str(text):
        if unicodedata.east_asian_width(ch) in ("W", "F") or ch in "⏚⏳⏲●◐▶":
            w += 2
        else:
            w += 1
    return w
_NV_GREEN = "#76B900"
_NV_GREEN_DIM = "#5a8c00"


# ── lazy state ──────────────────────────────────────────────────────────────
#
# The Switchyard UX is active only while BOTH hold, re-checked every poll:
#   1. the session's endpoint fingerprints as a Switchyard router, and
#   2. the currently selected /model is one of its configured routes
#      (e.g. "router") — pinning a catalog model or switching providers
#      returns the TUI to a completely stock look.

def _sw_ensure_init(self):
    """Idempotent; cheap after the first call. Never blocks the caller."""
    if getattr(self, "_sw_inited", False):
        return
    self._sw_inited = True
    self._sw_active = False
    self._sw_endpoint_root = None
    self._sw_url = None
    self._sw_snapshot = None
    self._sw_decisions = None
    self._sw_footer_mode = sw_settings.load_mode()
    self._sw_menu = None
    self._sw_detect_cache = {}
    self._sw_routes_cache = (None, [], 0.0)
    threading.Thread(target=_sw_poll_loop, args=(self,),
                     name="switchyard-poll", daemon=True).start()


def _sw_current_root(self):
    """Detect the session's endpoint, cached per URL (60s hit / 30s miss)."""
    provider_base_url = None
    try:
        import cli as _cli_mod
        prov = getattr(self, "requested_provider", None) or getattr(self, "provider", "")
        pcfg = (_cli_mod.CLI_CONFIG.get("providers") or {}).get(prov) or {}
        provider_base_url = pcfg.get("base_url") or pcfg.get("api") or pcfg.get("url")
    except Exception:
        pass
    now = time.monotonic()
    for cand in (
        getattr(self, "base_url", None),
        provider_base_url,
        os.environ.get("OPENAI_BASE_URL"),
        os.environ.get("OPENROUTER_BASE_URL"),
    ):
        norm = swc.normalize_root(cand)
        if not norm:
            continue
        cached = self._sw_detect_cache.get(norm)
        if cached and now - cached[1] < (60.0 if cached[0] else 30.0):
            root = cached[0]
        else:
            root = swc.detect(norm)
            self._sw_detect_cache[norm] = (root, now)
        if root:
            return root
    return None


def _sw_route_ids(self, root):
    """Configured route ids at *root*, cached ~10s (default id cached too)."""
    cached_root, ids, ts = self._sw_routes_cache
    now = time.monotonic()
    if cached_root == root and now - ts < 10.0:
        return ids
    rts, default = swc.routes(root)
    ids = [rt["id"] for rt in rts]
    self._sw_routes_cache = (root, ids, now)
    self._sw_default_id = default or (ids[0] if ids else None)
    return ids


def _sw_poll_loop(self):
    while True:
        try:
            root = _sw_current_root(self)
            self._sw_endpoint_root = root
            self._sw_url = root
            active = False
            if root:
                active = str(getattr(self, "model", "") or "") in _sw_route_ids(self, root)
                if active:
                    self._sw_snapshot = swc.stats(root)
                    self._sw_decisions = swc.decisions(root)
            if active != self._sw_active or active:
                self._sw_active = active
                try:
                    self._invalidate()
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(_POLL_SECS)


# ── rendering helpers (self-taking functions, shared by graft + subclass) ──

def _sw_transform_fragments(self, frags):
    mode = self._sw_footer_mode
    model_idx = None
    for i, frag in enumerate(frags):
        if len(frag) >= 2 and "status-bar-strong" in frag[0]:
            frags[i] = ("class:status-bar-nv",) + tuple(frag[1:])
            model_idx = i
            break

    if mode == "bar":
        served = _sw_served_model_short(self)
        if served and model_idx is not None:
            frags.insert(model_idx + 1, ("class:status-bar-nv-dim", f"→{served}"))
        seg = _sw_inline_segment(self)
        if seg:
            insert_at = next(
                (i + 1 for i, f in enumerate(frags)
                 if len(f) >= 2 and f[1].strip().endswith("%")),
                len(frags),
            )
            frags[insert_at:insert_at] = [
                ("class:status-bar-dim", " │ "),
                ("class:status-bar-nv", seg),
            ]
    elif mode == "min":
        st = self._sw_snapshot
        if st:
            frags += [
                ("class:status-bar-dim", " │ "),
                ("class:status-bar-nv", f"⏚ {swc.fmt_cost(swc.total_cost(st))}"),
            ]
    return frags


def _sw_row_fragments(self):
    try:
        st = self._sw_snapshot
        if not st:
            return [
                ("class:status-bar-nv", " ⏚ router "),
                ("class:status-bar-dim", "connecting…"),
            ]
        width = self._get_tui_terminal_width()
        reqs = st.get("total_requests", 0)
        cost = swc.fmt_cost(swc.total_cost(st))
        if width < 76:
            return [
                ("class:status-bar-nv", " ⏚ router"),
                ("class:status-bar-dim", " · "),
                ("class:status-bar", f"{reqs} req"),
                ("class:status-bar-dim", " · "),
                ("class:status-bar-nv", cost),
            ]
        sep = ("class:status-bar-dim", " │ ")
        tok = swc.fmt_tokens((st.get("total_tokens") or {}).get("total"))
        route = str(getattr(self, "model", "") or "").rsplit("/", 1)[-1][:26]
        frags = [("class:status-bar-nv", " ⏚ router")]
        if route and route != _sw_default_route(self):
            frags += [sep, ("class:status-bar", route)]
        frags += [
            sep,
            ("class:status-bar", f"{reqs} req"),
            sep,
            ("class:status-bar", f"{tok} tok"),
            sep,
            ("class:status-bar-nv", cost),
        ]
        tiers = swc.tier_counts(st)
        if tiers:
            tier_txt = " · ".join(f"{t} {n}" for t, n in sorted(tiers.items()))
            frags += [sep, ("class:status-bar-dim", tier_txt)]
        served = _sw_served_model_short(self)
        if served:
            frags += [sep, ("class:status-bar-nv-dim", f"→ {served}")]
        return frags
    except Exception:
        return [("class:status-bar-nv", " ⏚ router")]


def _sw_served_model_short(self):
    try:
        entry = swc.latest_decision(self._sw_decisions)
        if entry:
            return swc.short_model(entry.get("served_model"))[:26]
    except Exception:
        pass
    return ""


def _sw_inline_segment(self):
    st = self._sw_snapshot
    if not st:
        return ""
    return f"⏚ {st.get('total_requests', 0)}req {swc.fmt_cost(swc.total_cost(st))}"


def _sw_default_route(self):
    """The primary route id at the current endpoint ('router' by default).

    Reads only the cached value the poll loop / route-id cache maintains —
    this is called from render paths and must never touch the network."""
    return getattr(self, "_sw_default_id", None) or "router"


def _sw_switch_route(self, route):
    """Switch this session to a Switchyard route (same endpoint, new model id)."""
    _sw_ensure_init(self)
    root = getattr(self, "_sw_endpoint_root", None)
    if not root:
        return "this session's endpoint is not the router — see /router status"
    ids = _sw_route_ids(self, root)
    if route not in ids:
        return f"unknown route {route!r} — available: {', '.join(ids) or 'none'}"
    old = self.model
    if self.agent is not None:
        try:
            self.agent.switch_model(
                new_model=route,
                new_provider=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                api_mode=self.api_mode,
            )
        except Exception as exc:
            return f"switch failed ({exc}); staying on {old}"
    self.model = route
    self._sw_active = True  # poll loop confirms on its next cycle
    self._pending_model_switch_note = (
        f"[Note: router route was switched from {old} to {route}. "
        f"The router decides which upstream model serves each request.]"
    )
    try:
        self._invalidate()
    except Exception:
        pass
    return f"✓ route → {route}  (was {old})"


def _sw_extra_row_widget(self):
    """Build the dedicated-row widget (mode 'row')."""
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout import (
        ConditionalContainer,
        FormattedTextControl,
        Window,
    )
    return ConditionalContainer(
        Window(
            content=FormattedTextControl(lambda: _sw_row_fragments(self)),
            height=1,
            wrap_lines=False,
        ),
        filter=Condition(
            lambda: getattr(self, "_sw_active", False)
            and self._sw_footer_mode == "row"
            and getattr(self, "_status_bar_visible", True)
        ),
    )


def _sw_add_styles(styles):
    try:
        base = styles.get("status-bar", "")
        bg = next((t for t in base.split() if t.startswith("bg:")), "bg:#1a1a2e")
    except Exception:
        bg = "bg:#1a1a2e"
    styles["status-bar-nv"] = f"{bg} {_NV_GREEN} bold"
    styles["status-bar-nv-dim"] = f"{bg} {_NV_GREEN_DIM}"
    return styles


def _sw_usage_section(self):
    if getattr(self, "_sw_active", False):
        try:
            st = swc.stats(self._sw_url)
            dec = swc.decisions(self._sw_url)
            print()
            print(swc.render_usage(self._sw_url, st, dec, heading="router", color=False))
        except Exception:
            pass
    try:
        import sw_telemetry
        if sw_telemetry.state() == "on":
            stats = sw_telemetry.atof_stats()
            if stats:
                bd = sw_telemetry.atof_breakdown()
                bd_txt = " · ".join(f"{k} {v}" for k, v in bd.most_common(4)) if bd else ""
                print(f"── telemetry ──  {stats[1]} events ({bd_txt}) → {stats[0]}")
                print("  /telemetry sessions · /telemetry view <n>")
    except Exception:
        pass


def _sw_model_switch_preamble(self, cmd_original):
    """Handle /model for switchyard routes. Returns True when fully handled.

    Keys off the endpoint (not the active flag) so `/model switchyard` can
    switch INTO the Switchyard UX from a pinned catalog model.
    """
    root = getattr(self, "_sw_endpoint_root", None)
    if not root:
        return False
    try:
        parts = cmd_original.split(None, 1)
        raw = parts[1].strip() if len(parts) > 1 else ""
        ids = _sw_route_ids(self, root)
        if raw and not raw.startswith("-") and raw.split()[0] in ids:
            print("  " + _sw_switch_route(self, raw.split()[0]))
            return True
        if not raw and ids:
            current = self.model
            marks = ", ".join(
                ("▶ " if rt == current else "") + rt
                for rt in ids)
            print(f"  ⏚ router routes: {marks}")
            print("    switch with /model <route> — provider picker below")
    except Exception:
        pass
    return False


# ── type-to-search in the model picker ──────────────────────────────────────
#
# While the picker shows a model list in a grafted session, printable keys
# build a filter query (shown in the panel title as "🔎 query"), Backspace
# edits it, and the list narrows live. Matching is token-substring: every
# whitespace-separated token must appear somewhere in the model id.

def _sw_picker_filter_apply(self):
    state = self._model_picker_state
    if not state or state.get("stage") != "model":
        return
    full = state.get("sw_full_list")
    if full is None:
        full = list(state.get("model_list") or [])
        state["sw_full_list"] = full
        pd = state.get("provider_data") or {}
        state["sw_orig_name"] = pd.get("name", pd.get("slug", "Provider"))
    query = state.get("sw_query", "")
    tokens = query.lower().split()
    state["model_list"] = [m for m in full
                           if all(t in m.lower() for t in tokens)] if tokens else list(full)
    state["selected"] = 0
    state["_scroll_offset"] = 0
    pd = state.get("provider_data")
    if isinstance(pd, dict):
        base = state.get("sw_orig_name", "Provider")
        pd["name"] = f"{base}  🔎 {query}" if query else base
    try:
        self._invalidate(min_interval=0.0)
    except Exception:
        pass


def _sw_register_picker_search(self, kb):
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.keys import Keys

    def _searchable():
        state = getattr(self, "_model_picker_state", None)
        return bool(state) and state.get("stage") == "model"

    @kb.add(Keys.Any, filter=Condition(_searchable))
    def _sw_type(event):
        ch = event.data or ""
        if not ch or not ch.isprintable():
            return
        state = self._model_picker_state
        state["sw_query"] = state.get("sw_query", "") + ch
        _sw_picker_filter_apply(self)

    @kb.add("backspace", filter=Condition(_searchable))
    def _sw_backspace(event):
        state = self._model_picker_state
        q = state.get("sw_query", "")
        if q:
            state["sw_query"] = q[:-1]
            _sw_picker_filter_apply(self)


# ── interactive control panel (/switchyard) ────────────────────────────────
#
# Arrow-key panel in the same visual language as the native pickers:
# ↑/↓ move, Enter activates, ←/→ cycle the footer style, Esc closes.
# Strong/weak rows open the searchable model picker for just that tier.

_MENU_ITEMS = ("setup", "footer", "router", "provider", "strong", "weak", "save", "preflight", "telemetry", "route", "close")


def _sw_open_menu(self):
    _sw_ensure_init(self)
    self._sw_menu = {"selected": 0, "busy": "", "note": "", "preflight": None}
    try:
        self._invalidate(min_interval=0.0)
    except Exception:
        pass


def _sw_close_menu(self):
    self._sw_menu = None
    try:
        self._invalidate(min_interval=0.0)
    except Exception:
        pass


def _telemetry_row():
    import sw_telemetry
    st = sw_telemetry.state()
    if st == "no-lib":
        return ("telemetry", "Telemetry", "— relay lib not installed", "opt-in · needs nemo-relay in the venv")
    if st == "off":
        return ("telemetry", "Telemetry", "○ off", "Enter opts in (restart applies)")
    if st == "enabled":
        return ("telemetry", "Telemetry", "◐ enabled", "activates on first message · Enter turns off")
    stats = sw_telemetry.atof_stats()
    val = f"● on · {stats[1]} events" if stats else "● on"
    return ("telemetry", "Telemetry", val, "Enter turns off · /telemetry for detail")


def _sw_menu_rows(self):
    import sw_config
    opts = sw_config.load_last_opts()
    state = sw_config.router_state()
    running = bool(state and state.get("running"))
    port = (state or {}).get("port") or opts.get("port")
    connected = False
    try:
        connected = sw_config._MARK_BEGIN in (sw_config.HERMES_CONFIG.read_text())
    except Exception:
        pass
    m = self._sw_menu or {}
    pending = m.get("pending") or {}
    pf = m.get("preflight")
    pf_label = "press Enter to check keys" if pf is None else pf

    def tier_row(tier, label):
        pick = pending.get(tier)
        if pick:
            return (tier, label, f"● {swc.short_model(pick['model'])}", "unsaved — Save changes")
        return (tier, label, swc.short_model(opts.get(tier, "")), "Enter → searchable picker")

    n_pending = len(pending)
    save_val = f"{n_pending} unsaved change{'s' if n_pending != 1 else ''}" if n_pending else "—"
    configured = sw_config.CONFIG_PATH.exists()
    setup_val = "✓ configured" if (configured and running and connected) else (
        "▶ press Enter — one-shot" if not configured else "▶ finish setup — Enter")
    stale = bool(state and state.get("stale"))
    if running and stale:
        router_val, router_hint = f"● running :{port} — config changed", "Enter restarts to apply it"
    elif running:
        router_val, router_hint = f"● running :{port}", "Enter stops it"
    else:
        router_val, router_hint = "○ stopped", "Enter starts it"
    return [
        ("setup", "Quick setup", setup_val, "config → keys → router → provider"),
        ("footer", "Footer style", f"‹ {self._sw_footer_mode} ›", "←/→ cycles · applies live"),
        ("router", "Router", router_val, router_hint),
        ("provider", "Provider entry", "✓ connected" if connected else "— not connected",
         "Enter disconnects" if connected else "Enter connects (shows in /model)"),
        tier_row("strong", "Strong tier"),
        tier_row("weak", "Weak tier"),
        ("save", "Save changes", save_val,
         "write · preflight · restart router" if n_pending else "pick a tier first"),
        ("preflight", "Key preflight", pf_label, "1-token probe per tier"),
        _telemetry_row(),
        ("route", "Use router", "route this session" if self.model != _sw_default_route(self) else "▶ current model",
         "Enter → /model router"),
        ("close", "Close", "", "Esc discards unsaved picks"),
    ]


def _sw_menu_fragments(self):
    m = self._sw_menu
    if not m:
        return []
    # Rows gather process/file/network state — cache 1s so repaints are free.
    now = time.monotonic()
    cache = m.get("_rows_cache")
    if cache and now - cache[0] < 1.0:
        rows = cache[1]
    else:
        rows = _sw_menu_rows(self)
        m["_rows_cache"] = (now, rows)
    title = "⏚ Router"
    label_w = max(_dw(r[1]) for r in rows)
    value_w = max(_dw(r[2]) for r in rows)
    inner = max(52, max(2 + label_w + 2 + value_w + 2 + _dw(r[3]) + 3 for r in rows))
    lines = [("class:clarify-border", "╭─ "), ("class:status-bar-nv", title),
             ("class:clarify-border", " " + "─" * max(0, inner - _dw(title) - 3) + "╮\n")]

    def put(style_label, label, value, hint, selected):
        prefix = "❯ " if selected else "  "
        text = (prefix + label + " " * (label_w - _dw(label)) + "  "
                + value + " " * (value_w - _dw(value)) + "  ")
        lines.append(("class:clarify-border", "│ "))
        lines.append(("class:clarify-selected" if selected else style_label, text))
        pad = inner - _dw(text) - _dw(hint) - 3
        lines.append(("class:clarify-hint", hint + " " * max(0, pad)))
        lines.append(("class:clarify-border", " │\n"))

    for i, (key, label, value, hint) in enumerate(rows):
        put("class:clarify-choice", label, value, hint, i == m.get("selected", 0))
    if m.get("busy"):
        lines.append(("class:clarify-border", "│ "))
        busy = f"  ⏳ {m['busy']}"
        lines.append(("class:status-bar-nv", busy + " " * max(0, inner - _dw(busy) - 1)))
        lines.append(("class:clarify-border", " │\n"))
    if m.get("note"):
        for note_line in str(m["note"]).splitlines()[-14:]:
            lines.append(("class:clarify-border", "│ "))
            txt = f"  {note_line}"[: inner - 2]
            lines.append(("class:clarify-hint", txt + " " * max(0, inner - _dw(txt) - 1)))
            lines.append(("class:clarify-border", " │\n"))
    lines.append(("class:clarify-border", "╰" + "─" * inner + "╯\n"))
    return lines


def _sw_hint_widget(self):
    """One-line nudge shown only while nothing is configured yet."""
    import sw_config
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout import ConditionalContainer, FormattedTextControl, Window

    def frags():
        return [("class:status-bar-nv", " ⏚ router"),
                ("class:status-bar-dim", " installed but not set up — /router → Enter on Quick setup (~30s) ")]

    return ConditionalContainer(
        Window(FormattedTextControl(frags), height=1, wrap_lines=False),
        filter=Condition(lambda: getattr(self, "_sw_menu", None) is None
                         and not getattr(self, "_model_picker_state", None)
                         and not sw_config.CONFIG_PATH.exists()),
    )


def _sw_menu_widget(self):
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout import ConditionalContainer, FormattedTextControl, Window
    return ConditionalContainer(
        Window(FormattedTextControl(lambda: _sw_menu_fragments(self)), wrap_lines=True),
        filter=Condition(lambda: getattr(self, "_sw_menu", None) is not None
                         and not getattr(self, "_model_picker_state", None)),
    )


def _sw_menu_run(self, label, fn):
    """Run a slow action off the render thread, updating the busy line."""
    m = self._sw_menu
    if m is None or m.get("busy"):
        return

    def worker():
        try:
            note = fn()
            if self._sw_menu is not None:
                self._sw_menu["note"] = note or ""
        except Exception as exc:
            if self._sw_menu is not None:
                self._sw_menu["note"] = f"error: {exc}"
        finally:
            if self._sw_menu is not None:
                self._sw_menu["busy"] = ""
            try:
                self._invalidate(min_interval=0.0)
            except Exception:
                pass

    m["busy"] = label
    m["note"] = ""
    threading.Thread(target=worker, daemon=True).start()
    try:
        self._invalidate(min_interval=0.0)
    except Exception:
        pass


def _sw_menu_activate(self, direction=0):
    import sw_config
    import sw_settings
    m = self._sw_menu
    if not m:
        return
    key = _MENU_ITEMS[m.get("selected", 0) % len(_MENU_ITEMS)]

    if key == "setup":
        if direction:
            return
        def _setup():
            def stream(line):
                if self._sw_menu is not None:
                    note = self._sw_menu.get("note") or ""
                    self._sw_menu["note"] = (note + "\n" + line).strip()
                try:
                    self._invalidate(min_interval=0.0)
                except Exception:
                    pass
            ok, _lines = sw_config.setup(progress=stream)
            if self._sw_menu is not None and ok:
                self._sw_menu["preflight"] = "✓ all pass"
            return self._sw_menu.get("note") if self._sw_menu else ""
        _sw_menu_run(self, "running quick setup…", _setup)
        return
    if key == "footer":
        order = list(sw_settings.MODES)
        step = direction if direction else 1
        mode = order[(order.index(self._sw_footer_mode) + step) % len(order)]
        sw_settings.save_mode(mode)
        self._sw_footer_mode = mode
        try:
            self._invalidate(min_interval=0.0)
        except Exception:
            pass
        return
    if direction:  # ←/→ only means something on the footer row
        return

    if key == "router":
        state = sw_config.router_state()
        if state and state.get("running") and state.get("stale"):
            _sw_menu_run(self, "restarting router with saved config…",
                         lambda: sw_config.restart_router()[1])
        elif state and state.get("running"):
            _sw_menu_run(self, "stopping router…", lambda: sw_config.stop_router()[1])
        else:
            def _start():
                bin_path = sw_config.find_switchyard_bin()
                if not bin_path:
                    return "switchyard bin not found — /switchyard bin <path>"
                opts = sw_config.load_last_opts()
                if not sw_config.CONFIG_PATH.exists():
                    sw_config.write_config(opts)
                keys = sw_config.config_key_envs(sw_config.CONFIG_PATH)
                return sw_config.start_router(bin_path, sw_config.CONFIG_PATH,
                                              opts.get("port", "4100"),
                                              keys[0] if keys else "")[1]
            _sw_menu_run(self, "starting router…", _start)
    elif key == "provider":
        try:
            connected = sw_config._MARK_BEGIN in sw_config.HERMES_CONFIG.read_text()
        except Exception:
            connected = False
        if connected:
            _sw_menu_run(self, "disconnecting…", lambda: sw_config.disconnect_provider()[1])
        else:
            def _connect():
                state = sw_config.router_state()
                port = (state or {}).get("port") or sw_config.load_last_opts().get("port")
                root = swc.detect(f"http://127.0.0.1:{port}/v1", timeout=2.0)
                if not root:
                    return f"no router on :{port} — start it first"
                rts, _d = swc.routes(root)
                return sw_config.connect_provider(root + "/v1", [r["id"] for r in rts])[1]
            _sw_menu_run(self, "connecting…", _connect)
    elif key in ("strong", "weak"):
        msg = _sw_start_builder(self, "", only_tier=key, menu_mode=True)
        if msg:
            m["note"] = msg
        try:
            self._invalidate(min_interval=0.0)
        except Exception:
            pass
    elif key == "save":
        pending = dict(m.get("pending") or {})
        if not pending:
            m["note"] = "no unsaved tier picks — select Strong or Weak tier first"
            return

        def _apply():
            opts = sw_config.load_last_opts()
            for tier, pick in pending.items():
                opts.update({
                    tier: pick["model"], f"{tier}_format": pick["format"],
                    f"{tier}_base_url": pick["base_url"],
                    f"{tier}_key_env": pick["key_env"],
                })
            sw_config.apply_classifier_followup(opts)
            sw_config.write_config(opts)
            ok, report = sw_config.preflight_report(sw_config.preflight())
            if self._sw_menu is not None:
                self._sw_menu["pending"] = {}
                self._sw_menu["preflight"] = "✓ all pass" if ok else "✗ failing — see note"
            state = sw_config.router_state()
            if ok and state and state.get("running"):
                okr, msg = sw_config.restart_router()
                report += "\nsaved ✓ — " + msg
            elif state and state.get("running"):
                report += "\nsaved ✓ — fix keys, then Enter on the Router row to apply"
            else:
                report += "\nsaved ✓"
            return report

        _sw_menu_run(self, "saving + preflight + applying…", _apply)
    elif key == "telemetry":
        import sw_telemetry
        if sw_telemetry.state() == "no-lib":
            m["note"] = ("relay library not installed in the hermes venv — install it, "
                         "then Enter here to opt in")
            try:
                self._invalidate(min_interval=0.0)
            except Exception:
                pass
            return
        _sw_menu_run(self, "toggling telemetry…", lambda: sw_telemetry.toggle()[1])
    elif key == "preflight":
        def _pf():
            ok, report = sw_config.preflight_report(sw_config.preflight())
            if self._sw_menu is not None:
                self._sw_menu["preflight"] = "✓ all pass" if ok else "✗ failing — see note"
            return report
        _sw_menu_run(self, "probing upstream keys…", _pf)
    elif key == "route":
        if getattr(self, "_sw_endpoint_root", None):
            _sw_close_menu(self)
            print("  " + _sw_switch_route(self, _sw_default_route(self)))
            return
        try:
            connected = sw_config._MARK_BEGIN in sw_config.HERMES_CONFIG.read_text()
        except Exception:
            connected = False
        if not connected:
            m["note"] = "not set up yet — run Quick setup (first row) before routing"
            try:
                self._invalidate(min_interval=0.0)
            except Exception:
                pass
            return
        _sw_close_menu(self)
        # unrouted session with a provider entry: stock switch (provider
        # change), off the render thread — it does network resolution.
        threading.Thread(
            target=lambda: self._handle_model_switch("/model router"),
            daemon=True,
        ).start()
    elif key == "close":
        _sw_close_menu(self)


def _sw_register_menu_keys(self, kb):
    from prompt_toolkit.filters import Condition

    def _menu_open():
        return (getattr(self, "_sw_menu", None) is not None
                and not getattr(self, "_model_picker_state", None))

    cond = Condition(_menu_open)

    @kb.add("up", filter=cond)
    def _up(event):
        self._sw_menu["selected"] = (self._sw_menu.get("selected", 0) - 1) % len(_MENU_ITEMS)
        self._invalidate(min_interval=0.0)

    @kb.add("down", filter=cond)
    def _down(event):
        self._sw_menu["selected"] = (self._sw_menu.get("selected", 0) + 1) % len(_MENU_ITEMS)
        self._invalidate(min_interval=0.0)

    @kb.add("enter", filter=cond)
    def _enter(event):
        _sw_menu_activate(self)

    @kb.add("left", filter=cond)
    def _left(event):
        _sw_menu_activate(self, direction=-1)

    @kb.add("right", filter=cond)
    def _right(event):
        _sw_menu_activate(self, direction=1)

    @kb.add("escape", filter=cond)
    def _esc(event):
        _sw_close_menu(self)


# ── /switchyard build — interactive wizard over the native model picker ────
#
# Reuses Hermes's own /model picker modal twice (strong tier, then weak),
# listing only connected providers that Switchyard can call directly (a
# resolvable base_url + an API-key env var — OAuth-only providers are
# skipped). Each pick is translated into a Switchyard target automatically.

def _sw_provider_endpoint(self, slug, user_provs=None, custom_provs=None):
    """(base_url, key_env) for a Hermes provider slug, or (None, None)."""
    if slug in ("copilot", "github-copilot"):  # token-exchange auth — not a plain bearer key
        return None, None
    try:
        from hermes_cli.providers import resolve_provider_full
        pdef = resolve_provider_full(slug, user_provs, custom_provs)
        if pdef is not None and getattr(pdef, "base_url", ""):
            if getattr(pdef, "auth_type", "api_key") != "api_key":
                return None, None
            envs = list(getattr(pdef, "api_key_env_vars", ()) or ())
            if envs:
                return pdef.base_url, envs[0]
    except Exception:
        pass
    return None, None


def _sw_infer_format(slug, base_url, model):
    """Wire format for a tier target. Aggregators speak openai; native
    anthropic endpoints (and claude models on custom gateways) speak anthropic."""
    slug = (slug or "").lower()
    model = (model or "").lower()
    if slug in ("openrouter", "openai", "nvidia", "nous"):
        return "openai"
    if slug == "anthropic":
        return "anthropic"
    if "anthropic" in (base_url or "").lower():
        return "anthropic"
    if "claude" in model and slug not in ("openrouter",):
        return "anthropic"
    return "openai"


_SW_DEFAULTS_SLUG = "switchyard-default-endpoint"
_PROBE_CACHE = {}


def _sw_key_value(key_env):
    import sw_config
    return os.environ.get(key_env) or sw_config._key_from_hermes_env_file(key_env)


def _sw_builder_providers(self):
    """Connected providers usable as Switchyard targets, in picker-row shape.

    Prepends the router config's default endpoint as its own row (it usually
    isn't a Hermes provider but is exactly what the user's key works with),
    and auth-probes each real provider so rows whose key the endpoint rejects
    are visibly marked before the user picks a doomed model.
    """
    import sw_config
    from hermes_cli.inventory import build_models_payload, load_picker_context

    ctx = load_picker_context().with_overrides(
        current_provider=self.provider or "",
        current_model=self.model or "",
        current_base_url=self.base_url or "",
    )
    payload = build_models_payload(ctx, include_unconfigured=False, picker_hints=True)
    rows, skipped = [], []

    opts = sw_config.load_last_opts()
    default_url = opts.get("base_url", "")
    default_key = _sw_key_value(opts.get("key_env", ""))
    if default_url and default_key:
        ids = swc.list_models(default_url, default_key)
        if ids:
            host = default_url.split("//")[-1].split("/")[0]
            rows.append({
                "slug": _SW_DEFAULTS_SLUG,
                "name": f"Default endpoint · {host}",
                "models": ids,
                "total_models": len(ids),
                "is_current": False,
                "authenticated": True,
            })

    to_probe = []
    for row in payload.get("providers") or []:
        slug = row.get("slug") or ""
        if slug in ("router", "switchyard"):
            continue
        base_url, key_env = _sw_provider_endpoint(
            self, slug, ctx.user_providers, ctx.custom_providers)
        if not (base_url and key_env):
            skipped.append(slug)
            continue
        row = dict(row)
        row["is_current"] = False
        key_value = _sw_key_value(key_env)
        first_model = next(iter(row.get("models") or []), None)
        if not key_value:
            row["name"] = f"{row.get('name', slug)} ⚠ ${key_env} not set"
        elif first_model:
            to_probe.append((row, slug, base_url, key_env, key_value, first_model))
        rows.append(row)

    # Auth-probe in parallel with a 1h cache — sequential 8s probes made the
    # builder take tens of seconds to open with several providers.
    if to_probe:
        import concurrent.futures as _fut
        now = time.monotonic()

        def probe(item):
            row, slug, base_url, key_env, key_value, first_model = item
            ck = (base_url, key_env)
            hit = _PROBE_CACHE.get(ck)
            if hit and now - hit[1] < 3600:
                code = hit[0]
            else:
                code = swc.probe_upstream(
                    base_url, key_value, first_model,
                    _sw_infer_format(slug, base_url, first_model), timeout=8.0)
                _PROBE_CACHE[ck] = (code, now)
            if code in (401, 403):
                row["name"] = f"{row.get('name', slug)} ⚠ key fails here"

        with _fut.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(probe, to_probe))
    return rows, skipped, ctx


def _sw_start_builder(self, raw_args="", only_tier=None, menu_mode=False):
    import sw_config
    base_opts = sw_config.load_last_opts() if only_tier else None
    opts, unknown = sw_config.parse_kv(raw_args)
    if base_opts:
        base_opts.update({k: v for k, v in opts.items() if v != sw_config.DEFAULTS.get(k)})
        opts = base_opts
    if unknown:
        return "unrecognized: " + " ".join(unknown) + " — usage: /switchyard build [port=N ...]"
    try:
        rows, skipped, ctx = _sw_builder_providers(self)
    except Exception as exc:
        return f"could not list connected providers: {exc}"
    if not rows:
        return ("no connected providers usable as switchyard targets — "
                "switchyard needs providers with a base_url and an API-key env var "
                f"(skipped: {', '.join(skipped) or 'none'})")
    self._sw_builder = {"step": only_tier or "strong", "opts": opts, "rows": rows,
                        "ctx": ctx, "picking": False, "picks": {},
                        "only_tier": only_tier, "menu_mode": menu_mode}
    _sw_builder_open_picker(self)
    if menu_mode:
        return ""  # picker title carries the tier; pick returns to the panel
    note = f"  (skipped, no direct API key: {', '.join(skipped)})\n" if skipped else ""
    tier_word = (only_tier or "strong").upper()
    return (f"⏚ router build — pick the {tier_word} tier model — type to search 🔎\n{note}"
            "  ↑/↓ + Enter selects; Backspace edits the search; Cancel aborts")


def _sw_builder_open_picker(self):
    b = self._sw_builder
    b["picking"] = True
    label = "STRONG tier" if b["step"] == "strong" else "WEAK tier"
    self._open_model_picker(
        [dict(r) for r in b["rows"]],
        f"picking the {label}",
        "router build",
        user_provs=getattr(b["ctx"], "user_providers", None),
        custom_provs=getattr(b["ctx"], "custom_providers", None),
    )


def _sw_builder_capture(self, provider_data, chosen_model):
    """A model was picked inside the wizard. Advance or finish."""
    import sw_config
    b = self._sw_builder
    b["picking"] = False
    slug = provider_data.get("slug") or ""
    if slug == _SW_DEFAULTS_SLUG:
        opts = b["opts"]
        base_url, key_env = opts.get("base_url"), opts.get("key_env")
        fmt = "anthropic" if "claude" in chosen_model.lower() else "openai"
        slug = "default endpoint"
    else:
        base_url, key_env = _sw_provider_endpoint(
            self, slug, getattr(b["ctx"], "user_providers", None),
            getattr(b["ctx"], "custom_providers", None))
        fmt = _sw_infer_format(slug, base_url, chosen_model)
    pick = {"model": chosen_model, "slug": slug,
            "base_url": base_url, "key_env": key_env,
            "format": fmt}
    step = b["step"]
    if b.get("menu_mode"):
        self._sw_builder = None
        if self._sw_menu is not None:
            self._sw_menu.setdefault("pending", {})[step] = pick
            self._sw_menu["note"] = ""
        try:
            self._invalidate(min_interval=0.0)
        except Exception:
            pass
        return
    b["picks"][step] = pick
    if step == "strong" and not b.get("only_tier"):
        b["step"] = "weak"
        print(f"  ✓ strong: {chosen_model}  ({slug})")
        print("  ⏚ now pick the WEAK tier model (cheap/fast requests) — type to search 🔎")
        _sw_builder_open_picker(self)
        return
    print(f"  ✓ {step}: {chosen_model}  ({slug})")
    _sw_builder_finish(self)


def _sw_builder_finish(self):
    import sw_config
    b = self._sw_builder
    self._sw_builder = None
    opts = dict(b["opts"])
    for tier in ("strong", "weak"):
        pick = b["picks"].get(tier)
        if not pick:
            continue  # single-tier edit keeps the other tier as-is
        opts.update({
            tier: pick["model"], f"{tier}_format": pick["format"],
            f"{tier}_base_url": pick["base_url"], f"{tier}_key_env": pick["key_env"],
        })
    strong = b["picks"].get("strong") or {
        "model": opts["strong"], "slug": "kept", "format": opts["strong_format"],
        "key_env": opts.get("strong_key_env") or opts["key_env"],
        "base_url": opts.get("strong_base_url") or opts["base_url"]}
    weak = b["picks"].get("weak") or {
        "model": opts["weak"], "slug": "kept", "format": opts["weak_format"],
        "key_env": opts.get("weak_key_env") or opts["key_env"],
        "base_url": opts.get("weak_base_url") or opts["base_url"]}
    sw_config.apply_classifier_followup(opts)
    path = sw_config.write_config(opts)
    keys = ", ".join(f"${v}" for v in sorted({strong["key_env"], weak["key_env"]}))
    print(f"  ✓ wrote {path}")
    print(f"    strong: {strong['model']} ({strong['slug']}, {strong['format']})")
    print(f"    weak:   {weak['model']} ({weak['slug']}, {weak['format']})")
    print(f"    keys read at router start: {keys}")
    try:
        ok, report = sw_config.preflight_report(sw_config.preflight(path))
        print("  upstream key preflight:")
        for line in report.splitlines():
            print(f"    {line}")
        if not ok:
            print("  ⚠ fix the failing keys before /switchyard start — requests would 401 upstream")
    except Exception:
        pass
    print("  next: /router start → /router connect → /model router")
    try:
        self._invalidate()
    except Exception:
        pass


def _sw_builder_abort(self, b=None, reason="cancelled"):
    menu_mode = bool(((b or getattr(self, "_sw_builder", None)) or {}).get("menu_mode"))
    self._sw_builder = None
    if menu_mode:
        if self._sw_menu is not None:
            self._sw_menu["note"] = "tier pick cancelled"
        try:
            self._invalidate(min_interval=0.0)
        except Exception:
            pass
        return
    print(f"  ⏚ router build {reason} — run /router build to restart")


# ── class graft (called by the plugin at load time) ────────────────────────

def graft():
    """Wrap HermesCLI methods in place so stock `hermes` gets the footer.

    Idempotent; every wrapper falls back to the original method on any
    exception, so a Hermes upgrade degrades gracefully instead of crashing.
    """
    import cli as hermes_cli_mod

    base = hermes_cli_mod.HermesCLI
    if getattr(base, "_sw_grafted", False):
        return True

    orig_frags = base._get_status_bar_fragments
    orig_widgets = base._get_extra_tui_widgets
    orig_styles = base._build_tui_style_dict
    orig_usage = base._show_usage
    orig_model = base._handle_model_switch
    orig_pick = base._handle_model_picker_selection
    orig_close_picker = base._close_model_picker

    def patched_frags(self):
        frags = orig_frags(self)
        try:
            _sw_ensure_init(self)
            if not self._sw_active or not frags:
                return frags
            return _sw_transform_fragments(self, list(frags))
        except Exception:
            return frags

    def patched_widgets(self):
        widgets = list(orig_widgets(self))
        try:
            _sw_ensure_init(self)
            # panel first so the ⏚ row stays glued to the status bar below it
            widgets.append(_sw_menu_widget(self))
            widgets.append(_sw_hint_widget(self))
            widgets.append(_sw_extra_row_widget(self))
        except Exception:
            pass
        return widgets

    def patched_styles(self):
        styles = orig_styles(self)
        try:
            return _sw_add_styles(styles)
        except Exception:
            return styles

    def patched_usage(self):
        orig_usage(self)
        try:
            _sw_ensure_init(self)
            _sw_usage_section(self)
        except Exception:
            pass

    def patched_model(self, cmd_original):
        try:
            _sw_ensure_init(self)
            # `/model router` from an unrouted session: the provider entry
            # also surfaces via the legacy custom-provider view, so a bare
            # model name is ambiguous — pin the provider explicitly. Before
            # setup has run there IS no provider entry: point at Quick setup
            # instead of letting the switch fail with "unknown provider".
            parts = cmd_original.split()
            if (len(parts) == 2 and parts[1] in ("router", "switchyard")
                    and not getattr(self, "_sw_endpoint_root", None)):
                import sw_config
                try:
                    connected = sw_config._MARK_BEGIN in sw_config.HERMES_CONFIG.read_text()
                except Exception:
                    connected = False
                if not connected:
                    print("  ⏚ the router isn't set up yet — /router → Enter on Quick setup (~30s)")
                    return
                cmd_original = "/model router --provider router"
        except Exception:
            pass
        try:
            if _sw_model_switch_preamble(self, cmd_original):
                return
        except Exception:
            pass
        return orig_model(self, cmd_original)

    def patched_pick(self, persist_global=False):
        # /switchyard build wizard: divert model picks into the builder
        # instead of switching the session model.
        b = getattr(self, "_sw_builder", None)
        if b and b.get("picking"):
            try:
                state = self._model_picker_state or {}
                if state.get("stage") == "model":
                    model_list = state.get("model_list") or []
                    selected = state.get("selected", 0)
                    if selected < len(model_list):
                        provider_data = state.get("provider_data") or {}
                        chosen = model_list[selected]
                        orig_close_picker(self)
                        _sw_builder_capture(self, provider_data, chosen)
                        return
            except Exception:
                self._sw_builder = None
        result = orig_pick(self, persist_global)
        try:
            state = self._model_picker_state
            if state and state.get("stage") == "provider" and state.get("sw_orig_name"):
                pd = state.get("provider_data")
                if isinstance(pd, dict):
                    pd["name"] = state["sw_orig_name"]
                state.pop("sw_query", None)
                state.pop("sw_full_list", None)
                state.pop("sw_orig_name", None)
        except Exception:
            pass
        return result

    def patched_close_picker(self):
        b = getattr(self, "_sw_builder", None)
        orig_close_picker(self)
        if b and b.get("picking"):
            try:
                _sw_builder_abort(self, b)
            except Exception:
                self._sw_builder = None

    orig_keys = base._register_extra_tui_keybindings

    def patched_keys(self, kb, *, input_area):
        orig_keys(self, kb, input_area=input_area)
        try:
            _sw_register_picker_search(self, kb)
            _sw_register_menu_keys(self, kb)
        except Exception:
            pass

    base._get_status_bar_fragments = patched_frags
    base._get_extra_tui_widgets = patched_widgets
    base._build_tui_style_dict = patched_styles
    base._show_usage = patched_usage
    base._handle_model_switch = patched_model
    base._handle_model_picker_selection = patched_pick
    base._close_model_picker = patched_close_picker
    base._register_extra_tui_keybindings = patched_keys
    base._sw_switch_route = _sw_switch_route
    base._sw_start_builder = _sw_start_builder
    base._sw_open_menu = _sw_open_menu
    base._sw_grafted = True
    return True
