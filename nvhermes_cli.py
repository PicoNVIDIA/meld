"""Switchyard footer for Hermes — grafted onto HermesCLI at plugin load.

The plugin calls graft() when Hermes loads it (same process), wrapping a few
HermesCLI methods on the CLASS so the stock `hermes` command gets the footer,
green model name, /usage section, and /model route quick-switch — no separate
launcher needed. Every wrapper falls back to stock behavior on any exception,
and everything stays dormant unless the session's endpoint fingerprints as a
Switchyard router.

State is initialized lazily on first render (_sw_ensure_init): detection and
stats polling run in a daemon thread, never on the render path.

A SwitchyardCLI subclass is kept for the legacy `nvhermes` wrapper; grafted
wrappers no-op for it (the subclass methods already do the work).

Footer styles (persisted via sw_settings, switched live with /switchyard
footer): row (default) · bar · min · off.
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
_NV_GREEN = "#76B900"
_NV_GREEN_DIM = "#5a8c00"


# ── lazy state ──────────────────────────────────────────────────────────────
#
# The Switchyard UX is active only while BOTH hold, re-checked every poll:
#   1. the session's endpoint fingerprints as a Switchyard router, and
#   2. the currently selected /model is one of its configured routes
#      (e.g. "switchyard") — pinning a catalog model or switching providers
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
    """Configured route ids at *root*, cached ~10s."""
    cached_root, ids, ts = self._sw_routes_cache
    now = time.monotonic()
    if cached_root == root and now - ts < 10.0:
        return ids
    rts, _default = swc.routes(root)
    ids = [rt["id"] for rt in rts]
    self._sw_routes_cache = (root, ids, now)
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
                ("class:status-bar-nv", " ⏚ switchyard "),
                ("class:status-bar-dim", "connecting…"),
            ]
        width = self._get_tui_terminal_width()
        reqs = st.get("total_requests", 0)
        cost = swc.fmt_cost(swc.total_cost(st))
        if width < 76:
            return [
                ("class:status-bar-nv", " ⏚ swyd"),
                ("class:status-bar-dim", " · "),
                ("class:status-bar", f"{reqs} req"),
                ("class:status-bar-dim", " · "),
                ("class:status-bar-nv", cost),
            ]
        sep = ("class:status-bar-dim", " │ ")
        tok = swc.fmt_tokens((st.get("total_tokens") or {}).get("total"))
        route = str(getattr(self, "model", "") or "").rsplit("/", 1)[-1][:26]
        frags = [("class:status-bar-nv", " ⏚ switchyard")]
        if route and route != "switchyard":
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
        return [("class:status-bar-nv", " ⏚ switchyard")]


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


def _sw_switch_route(self, route):
    """Switch this session to a Switchyard route (same endpoint, new model id)."""
    _sw_ensure_init(self)
    root = getattr(self, "_sw_endpoint_root", None)
    if not root:
        return "this session's endpoint is not a switchyard router — see /switchyard status"
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
        f"[Note: switchyard route was switched from {old} to {route}. "
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
    if not getattr(self, "_sw_active", False):
        return
    try:
        st = swc.stats(self._sw_url)
        dec = swc.decisions(self._sw_url)
        print()
        print(swc.render_usage(self._sw_url, st, dec, heading="switchyard", color=False))
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
            print(f"  ⏚ switchyard routes: {marks}")
            print("    switch with /model <route> — provider picker below")
    except Exception:
        pass
    return False


# ── class graft (called by the plugin at load time) ────────────────────────

def graft():
    """Wrap HermesCLI methods in place so stock `hermes` gets the footer.

    Idempotent. Wrappers no-op for SwitchyardCLI instances (legacy nvhermes
    wrapper — its own overrides already apply) and fall back to the original
    method on any exception.
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

    def patched_frags(self):
        frags = orig_frags(self)
        if getattr(self, "_sw_wrapper", False):
            return frags
        try:
            _sw_ensure_init(self)
            if not self._sw_active or not frags:
                return frags
            return _sw_transform_fragments(self, list(frags))
        except Exception:
            return frags

    def patched_widgets(self):
        widgets = list(orig_widgets(self))
        if getattr(self, "_sw_wrapper", False):
            return widgets
        try:
            _sw_ensure_init(self)
            widgets.append(_sw_extra_row_widget(self))
        except Exception:
            pass
        return widgets

    def patched_styles(self):
        styles = orig_styles(self)
        if getattr(self, "_sw_wrapper", False):
            return styles
        try:
            return _sw_add_styles(styles)
        except Exception:
            return styles

    def patched_usage(self):
        orig_usage(self)
        if getattr(self, "_sw_wrapper", False):
            return
        try:
            _sw_ensure_init(self)
            _sw_usage_section(self)
        except Exception:
            pass

    def patched_model(self, cmd_original):
        if not getattr(self, "_sw_wrapper", False):
            try:
                _sw_ensure_init(self)
                if _sw_model_switch_preamble(self, cmd_original):
                    return
            except Exception:
                pass
        return orig_model(self, cmd_original)

    base._get_status_bar_fragments = patched_frags
    base._get_extra_tui_widgets = patched_widgets
    base._build_tui_style_dict = patched_styles
    base._show_usage = patched_usage
    base._handle_model_switch = patched_model
    base._sw_switch_route = _sw_switch_route
    base._sw_grafted = True
    return True


# ── legacy wrapper subclass (nvhermes) ──────────────────────────────────────

try:
    from cli import HermesCLI as _HermesCLI
except Exception:  # pragma: no cover — module usable without hermes on path
    _HermesCLI = object


class SwitchyardCLI(_HermesCLI):
    _sw_wrapper = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _sw_ensure_init(self)

    def _build_tui_style_dict(self):
        return _sw_add_styles(super()._build_tui_style_dict())

    def _get_status_bar_fragments(self):
        frags = super()._get_status_bar_fragments()
        if not getattr(self, "_sw_active", False) or not frags:
            return frags
        try:
            return _sw_transform_fragments(self, list(frags))
        except Exception:
            return frags

    def _get_extra_tui_widgets(self):
        widgets = list(super()._get_extra_tui_widgets())
        try:
            widgets.append(_sw_extra_row_widget(self))
        except Exception:
            pass
        return widgets

    def _sw_switch_route(self, route):
        return _sw_switch_route(self, route)

    def _handle_model_switch(self, cmd_original):
        try:
            if _sw_model_switch_preamble(self, cmd_original):
                return
        except Exception:
            pass
        return super()._handle_model_switch(cmd_original)

    def _show_usage(self):
        super()._show_usage()
        _sw_usage_section(self)
