"""SwitchyardCLI — HermesCLI subclass that renders the Switchyard footer.

Uses Hermes's protected TUI extension hooks (_build_tui_style_dict,
_get_extra_tui_widgets) plus a defensive override of the internal
_get_status_bar_fragments; every override falls back to stock rendering on
any exception, so a Hermes upgrade degrades gracefully instead of crashing.

Footer styles (persisted via sw_settings, switched live with /nvfooter):
  row  — dedicated Switchyard line above the stock status bar (default)
  bar  — Switchyard segments spliced into the stock bar, with →served-model
  min  — stock bar plus a single trailing cost segment
  off  — no Switchyard segments (model name still green while routed)
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

_DIR = Path(__file__).resolve().parent
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

import sw_settings
import switchyard_client as swc

from cli import HermesCLI

_POLL_SECS = 2.0
_NV_GREEN = "#76B900"
_NV_GREEN_DIM = "#5a8c00"


class SwitchyardCLI(HermesCLI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sw_footer_mode = sw_settings.load_mode()
        self._sw_snapshot = None
        self._sw_decisions = None
        # Green/footer activate only when THIS session's endpoint is a
        # Switchyard router — a router merely running nearby doesn't count.
        # The endpoint can arrive as self.base_url (config model.base_url /
        # OPENROUTER_BASE_URL) or via a provider profile's env base_url.
        import os as _os

        self._sw_url = None
        for cand in (
            getattr(self, "base_url", None),
            _os.environ.get("OPENAI_BASE_URL"),
            _os.environ.get("OPENROUTER_BASE_URL"),
        ):
            self._sw_url = swc.detect(cand)
            if self._sw_url:
                break
        self._sw_active = self._sw_url is not None
        if self._sw_active:
            threading.Thread(
                target=self._sw_poll_loop, name="switchyard-poll", daemon=True
            ).start()

    # ── polling ────────────────────────────────────────────────────────────
    def _sw_poll_loop(self):
        while True:
            try:
                self._sw_snapshot = swc.stats(self._sw_url)
                self._sw_decisions = swc.decisions(self._sw_url)
                try:
                    self._invalidate()
                except Exception:
                    pass
            except Exception:
                pass
            time.sleep(_POLL_SECS)

    # ── styles (protected hook) ────────────────────────────────────────────
    def _build_tui_style_dict(self):
        styles = super()._build_tui_style_dict()
        try:
            base = styles.get("status-bar", "")
            bg = next((t for t in base.split() if t.startswith("bg:")), "bg:#1a1a2e")
        except Exception:
            bg = "bg:#1a1a2e"
        styles["status-bar-nv"] = f"{bg} {_NV_GREEN} bold"
        styles["status-bar-nv-dim"] = f"{bg} {_NV_GREEN_DIM}"
        return styles

    # ── stock bar transform (all styles) ───────────────────────────────────
    def _get_status_bar_fragments(self):
        frags = super()._get_status_bar_fragments()
        if not self._sw_active or not frags:
            return frags
        try:
            return self._sw_transform_fragments(list(frags))
        except Exception:
            return frags

    def _sw_transform_fragments(self, frags):
        mode = self._sw_footer_mode
        model_idx = None
        for i, frag in enumerate(frags):
            if len(frag) >= 2 and "status-bar-strong" in frag[0]:
                frags[i] = ("class:status-bar-nv",) + tuple(frag[1:])
                model_idx = i
                break

        if mode == "bar":
            served = self._sw_served_model_short()
            if served and model_idx is not None:
                frags.insert(model_idx + 1, ("class:status-bar-nv-dim", f"→{served}"))
            seg = self._sw_inline_segment()
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

    # ── dedicated row (protected hook) ─────────────────────────────────────
    def _get_extra_tui_widgets(self):
        widgets = list(super()._get_extra_tui_widgets())
        try:
            from prompt_toolkit.filters import Condition
            from prompt_toolkit.layout import (
                ConditionalContainer,
                FormattedTextControl,
                Window,
            )
        except Exception:
            return widgets
        widgets.append(
            ConditionalContainer(
                Window(
                    content=FormattedTextControl(self._sw_row_fragments),
                    height=1,
                    wrap_lines=False,
                ),
                filter=Condition(
                    lambda: self._sw_active
                    and self._sw_footer_mode == "row"
                    and getattr(self, "_status_bar_visible", True)
                ),
            )
        )
        return widgets

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
            frags = [
                ("class:status-bar-nv", " ⏚ switchyard"),
                sep,
                ("class:status-bar", route),
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
            served = self._sw_served_model_short()
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

    # ── native /usage section ──────────────────────────────────────────────
    def _show_usage(self):
        super()._show_usage()
        if not self._sw_active:
            return
        try:
            st = swc.stats(self._sw_url)
            dec = swc.decisions(self._sw_url)
            print()
            print(swc.render_usage(self._sw_url, st, dec, heading="switchyard", color=False))
        except Exception:
            pass
