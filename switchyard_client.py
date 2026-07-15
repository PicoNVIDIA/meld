"""Minimal stdlib client for a NeMo Switchyard router.

Shared by the plugin commands (/nvusage, /nvfooter) and the nvhermes wrapper
CLI. Every network call is bounded by a short timeout and returns None on any
failure so callers render "not detected" instead of surfacing errors.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_CANDIDATES = ("http://127.0.0.1:4000", "http://127.0.0.1:4100")

GREEN = "\x1b[38;2;118;185;0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
RST = "\x1b[0m"


def _get_json(url, timeout=0.5, method="GET"):
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def normalize_root(url):
    """'http://host:4100/v1/' -> 'http://host:4100' (None when empty)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[: -len("/v1")].rstrip("/")
    return url or None


def detect(base_url, timeout=0.5):
    """Return the Switchyard root URL iff *base_url* points at one, else None.

    Fingerprint order: /v1/models entries with owned_by == "switchyard" (or the
    Switchyard-specific default_model/model_pool keys), then /health + a
    reachable /v1/routing/stats as fallback.
    """
    root = normalize_root(base_url)
    if not root:
        return None
    models = _get_json(root + "/v1/models", timeout=timeout)
    if isinstance(models, dict):
        data = models.get("data") or []
        for entry in data:
            if isinstance(entry, dict) and entry.get("owned_by") == "switchyard":
                return root
        if "model_pool" in models or "default_model" in models:
            return root
    health = _get_json(root + "/health", timeout=timeout)
    if isinstance(health, dict) and health.get("status") == "ok":
        if _get_json(root + "/v1/routing/stats", timeout=timeout) is not None:
            return root
    return None


def resolve_url(session_base_url=None):
    """Find a Switchyard root for inspection commands.

    Precedence: the session's own base_url, $SWITCHYARD_URL, then common
    localhost ports. Only the session base_url implies the session is actually
    routed through Switchyard — the rest are for /nvusage inspection.
    """
    candidates = [session_base_url, os.environ.get("SWITCHYARD_URL")]
    candidates.extend(DEFAULT_CANDIDATES)
    for cand in candidates:
        root = detect(cand)
        if root:
            return root
    return None


def routes(root, timeout=1.0):
    """Configured routes only (not the passthrough catalog).

    Returns (routes, default_id): routes is a list of
    {id, profile, context_window} for /v1/models entries whose
    switchyard.profile is not 'passthrough'.
    """
    models = _get_json(root + "/v1/models", timeout=timeout)
    if not isinstance(models, dict):
        return [], None
    out = []
    for entry in models.get("data") or []:
        if not isinstance(entry, dict) or entry.get("owned_by") != "switchyard":
            continue
        meta = entry.get("switchyard") or {}
        if meta.get("profile") == "passthrough":
            continue
        out.append({
            "id": entry.get("id"),
            "profile": meta.get("profile") or "?",
            "context_window": (entry.get("capabilities") or {}).get("context_window"),
        })
    return out, models.get("default_model")


def stats(root, timeout=0.5):
    return _get_json(root + "/v1/routing/stats", timeout=timeout)


def decisions(root, timeout=0.5):
    return _get_json(root + "/v1/routing/decisions", timeout=timeout)


def health_ok(root, timeout=0.5):
    h = _get_json(root + "/health", timeout=timeout)
    return isinstance(h, dict) and h.get("status") == "ok"


def reset(root, timeout=2.0):
    return _get_json(root + "/v1/stats/reset", timeout=timeout, method="POST")


def list_models(base_url, api_key, timeout=6.0):
    """Model ids from an OpenAI-compatible endpoint (auth'd GET /models)."""
    url = (base_url or "").rstrip("/") + "/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict) and m.get("id")]
    except Exception:
        return []


def probe_upstream(base_url, api_key, model, fmt="openai", timeout=15.0):
    """Auth preflight: a 1-token chat completion against the endpoint.

    A models-list GET is useless here — some endpoints serve their catalog
    publicly (integrate.api.nvidia.com) — so we exercise the same call chat
    traffic uses. Returns the HTTP status (200 = key+model work, 401/403 =
    key rejected, 400/404/422 = auth ok but model unavailable), or None when
    unreachable. The key is sent to the endpoint only.
    """
    body = json.dumps({
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    if (fmt or "openai") == "anthropic":
        url = (base_url or "").rstrip("/") + "/messages"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
    else:
        url = (base_url or "").rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json"}
    try:
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------

def fmt_tokens(n):
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_cost(v):
    try:
        return f"${float(v or 0):.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def short_model(name):
    """'aws/anthropic/bedrock-claude-opus-4-8' -> 'bedrock-claude-opus-4-8'."""
    if not name:
        return ""
    return str(name).rsplit("/", 1)[-1]


def total_cost(st):
    est = (st or {}).get("cost_estimate") or {}
    if "total_cost" in est:
        return float(est.get("total_cost") or 0)
    models = (st or {}).get("models") or {}
    return sum(float(m.get("estimated_cost_usd") or 0) for m in models.values())


def model_cost(st, name):
    est_models = ((st or {}).get("cost_estimate") or {}).get("models") or {}
    if name in est_models:
        return float(est_models[name].get("total_cost") or 0)
    return float(((st or {}).get("models") or {}).get(name, {}).get("estimated_cost_usd") or 0)


def tier_counts(st):
    """{'weak': 30, 'strong': 12} — calls per tier (short model name when untiered)."""
    tiers = (st or {}).get("tiers") or {}
    if tiers:
        return {t: int(v.get("calls") or 0) for t, v in tiers.items()}
    counts = {}
    for name, m in ((st or {}).get("models") or {}).items():
        label = m.get("tier") or short_model(name)
        counts[label] = counts.get(label, 0) + int(m.get("calls") or 0)
    return counts


def latest_decision(dec):
    """Most recent per-request decision record, or None."""
    recent = (((dec or {}).get("routing_decisions") or {}).get("recent")) or []
    if not recent:
        return None
    return recent[-1]


def render_usage(root, st, dec, heading="switchyard usage", color=True):
    """Human-readable usage report. Shared by /nvusage (ANSI) and the native
    /usage section (plain — that print path sanitizes escape bytes)."""
    g, d, b, r = (GREEN, DIM, BOLD, RST) if color else ("", "", "", "")
    lines = [f"{g}{b}── {heading} ──{r}  {d}{root}{r}"]
    if not st:
        lines.append(f"  {d}stats endpoint unreachable — is the router running with stats enabled?{r}")
        return "\n".join(lines)

    tok = st.get("total_tokens") or {}
    cache_read = tok.get("cached", tok.get("cache_read"))
    lines.append(
        f"  requests {b}{st.get('total_requests', 0)}{r}"
        f"  ·  tokens {b}{fmt_tokens(tok.get('total'))}{r}"
        f" {d}(prompt {fmt_tokens(tok.get('prompt'))}, completion {fmt_tokens(tok.get('completion'))},"
        f" reasoning {fmt_tokens(tok.get('reasoning'))},"
        f" cache r/w {fmt_tokens(cache_read)}/{fmt_tokens(tok.get('cache_creation'))}){r}"
        f"  ·  est cost {g}{b}{fmt_cost(total_cost(st))}{r}"
    )

    models = st.get("models") or {}
    if models:
        lines.append(f"  {d}{'model':<44} {'tier':<8} {'calls':>6} {'tokens':>9} {'cost':>8}{r}")
        for name, m in sorted(models.items(), key=lambda kv: -int(kv[1].get("calls") or 0)):
            lines.append(
                f"  {short_model(name):<44} {str(m.get('tier') or '-'):<8}"
                f" {int(m.get('calls') or 0):>6} {fmt_tokens(m.get('total_tokens')):>9}"
                f" {fmt_cost(model_cost(st, name)):>8}"
            )

    recent = (((dec or {}).get("routing_decisions") or {}).get("recent")) or []
    if recent:
        lines.append(f"  {d}recent decisions:{r}")
        for entry in recent[-5:]:
            conf = entry.get("confidence")
            conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "-"
            lat = entry.get("latency_ms")
            lat_s = f"{int(lat)}ms" if isinstance(lat, (int, float)) else "-"
            lines.append(
                f"    {d}·{r} {entry.get('tier') or '-'} {d}({entry.get('source') or '-'}, conf {conf_s}){r}"
                f" → {g}{short_model(entry.get('served_model')) or '-'}{r}"
                f"  {entry.get('outcome') or '-'} {d}{lat_s}{r}"
            )
    return "\n".join(lines)
