"""Whale Score, severity, confidence and explanation (CONTEXT §15-17, §29, §31)."""
from __future__ import annotations

import time

from . import db
from .baseline import build_baseline
from .detect import evaluate_window, money

LOOKBACK_EVAL_S = 15 * 60  # baseline excludes the most recent 15 minutes


def whale_score(ev, weights):
    avail = {k: w for k, w in weights.items() if k in ev.signals}
    total_w = sum(avail.values())
    if not total_w:
        return 0.0
    return 100 * sum(ev.signals[k].strength * w for k, w in avail.items()) / total_w


def severity(score, bands):
    for floor, name in bands:
        if score >= floor:
            return name
    return "NORMAL"


def context_labels(ev, base, market, now, cfg):
    """Benign explanations worth flagging rather than calling everything a whale (§29)."""
    labels = []
    close_t, open_t = market.get("close_time"), market.get("open_time")
    if close_t and 0 <= close_t - ev.end <= cfg["near_close_minutes"] * 60:
        labels.append(f"near market close ({(close_t - ev.end) / 60:.0f} min) — activity often normal here")
    if open_t and ev.end - open_t <= cfg["new_market_hours"] * 3600:
        labels.append("recently opened market — baseline still forming")
    if base.avg_volume.get(300, 0) < cfg["thin_market_5m_volume"]:
        labels.append("thin market — small absolute flows produce large ratios")
    if ev.n_trades == 1:
        labels.append("single trade — could be one-off or erroneous print")
    return labels


def confidence(ev, base, platform, cfg):
    reasons = []
    strong = [k for k, s in ev.signals.items() if s.strength >= 0.5]
    if base.n_trades < cfg["min_baseline_trades"]:
        level = "LOW"
        reasons.append(f"insufficient baseline ({base.n_trades} prior trades)")
    elif len(strong) >= 3 and base.span_s >= 6 * 3600:
        level = "HIGH"
        reasons.append(f"{len(strong)} independent signals strong ({', '.join(strong)})")
    elif len(strong) >= 2:
        level = "MEDIUM"
        reasons.append(f"{len(strong)} strong signals ({', '.join(strong)})")
    else:
        level = "LOW"
        reasons.append("few independent signals")
    if base.span_s < 6 * 3600:
        reasons.append(f"only {base.span_s / 3600:.1f}h of history")
    if "liquidity" not in ev.signals:
        reasons.append("liquidity unknown")
    if platform == "kalshi":
        reasons.append("trader identity not available on Kalshi")
    return level, reasons


def load_baseline(conn, platform, market_id, window_start, cfg):
    history = db.trades_between(conn, platform, market_id,
                                window_start - cfg["baseline_days"] * 86400, window_start - 1e-6)
    return build_baseline(history, window_start)


def analyze_market(conn, platform, market_id, cfg, now=None):
    """Score the strongest window for one market. Returns an alert dict or None."""
    now = now or time.time()
    market = dict(db.get_market(conn, platform, market_id) or {})
    recent_hour = db.trades_between(conn, platform, market_id, now - 3 * 3600, now)
    if not recent_hour:
        return None
    end = recent_hour[-1]["ts"]  # anchor on latest trade (feeds can lag wall-clock)
    recent = [t for t in recent_hour if t["ts"] > end - LOOKBACK_EVAL_S]
    if sum(t["notional"] for t in recent) < cfg["min_window_notional"]:
        return None
    base = load_baseline(conn, platform, market_id, end - LOOKBACK_EVAL_S, cfg)
    if base.n_trades < 10:
        return {"needs_backfill": True}
    snap = db.latest_snapshot(conn, platform, market_id)
    liq = snap["liquidity"] if snap else None
    liq_kind = snap["liquidity_kind"] if snap else None
    acc_trades = [t for t in recent_hour if t["ts"] > end - cfg["accumulation_minutes"] * 60]
    labels = (market.get("yes_label") or "YES", market.get("no_label") or "NO")

    best, best_score = None, -1.0
    for w in cfg["windows_minutes"]:
        ev = evaluate_window(recent, base, end, w, liq, liq_kind, acc_trades, labels, cfg["scaling"])
        if ev:
            sc = whale_score(ev, cfg["weights"])
            if sc > best_score:
                best, best_score = ev, sc
    if not best:
        return None

    sev = severity(best_score, cfg["severity"])
    conf, conf_reasons = confidence(best, base, platform, cfg)
    ctx = context_labels(best, base, market, now, cfg)
    d_label = labels[0] if best.direction == "YES" else labels[1]
    detected = (f"{money(best.dir_notional)} {best.direction} flow over {best.window_min} min "
                f"({best.n_trades} trades, {money(best.total_notional)} total)")
    ranked = sorted(best.signals.items(), key=lambda kv: -kv[1].strength)
    why = [s.text for _, s in ranked if s.text and s.strength > 0] or \
          [s.text for _, s in ranked if s.text][:2]
    vol = best.signals.get("volume")
    return {
        "ts": end,
        "platform": platform,
        "market_id": market_id,
        "title": market.get("title") or market_id,
        "direction": best.direction,
        "score": round(best_score, 1),
        "severity": sev,
        "confidence": conf,
        "headline": f"{sev} — Score {best_score:.0f}/100",
        "evidence": {
            "direction_label": d_label,
            "detected": detected,
            "why": why,
            "notes": best.notes,
            "context": ctx,
            "confidence_reasons": conf_reasons,
            "signals": {k: round(s.strength, 3) for k, s in best.signals.items()},
            "window_min": best.window_min,
            "dir_notional": best.dir_notional,
            "volume_text": vol.text if vol else None,
            "price_from": best.price_from,
            "price_to": best.price_to,
            "url": market.get("url"),
            "baseline": {"trades": base.n_trades, "hours": round(base.span_s / 3600, 1),
                         "median_trade": round(base.median_trade, 2)},
        },
    }
