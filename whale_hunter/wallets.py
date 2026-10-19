"""New / low-history / reactivated wallet large-position detector (CONTEXT §23).

Describes observed behavior only. A new wallet with a large position is evidence of unusual
behavior, not of private information.
"""
from __future__ import annotations

import time
from collections import defaultdict

from . import db
from .detect import clamp01, log_strength, money
from .score import load_baseline
from .track import describe, get_track

NEWNESS = {"NEW WALLET": 1.0, "REACTIVATED WALLET": 0.8, "LOW-HISTORY WALLET": 0.6}


def classify(profile, position_start, wc):
    """Descriptive classes, most significant first. Empty list = established wallet."""
    out = []
    first = profile.get("first_seen_ts")
    if first is not None and position_start - first <= wc["new_wallet_days"] * 86400:
        out.append("NEW WALLET")
    prior = profile.get("last_prior_trade_ts")
    if prior is not None and position_start - prior >= wc["dormant_days"] * 86400:
        out.append("REACTIVATED WALLET")
    n = profile.get("markets_traded")
    if n is not None and n <= wc["low_history_markets"]:
        out.append("LOW-HISTORY WALLET")
    return out


def ago(seconds):
    if seconds < 3600:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} hours"
    return f"{seconds / 86400:.0f} days"


def positions(trades, wc):
    """Per-wallet directional flow in the window."""
    by = defaultdict(lambda: {"YES": 0.0, "NO": 0.0, "trades": []})
    for t in trades:
        if t.get("wallet"):
            by[t["wallet"]][t["direction"]] += t["notional"]
            by[t["wallet"]]["trades"].append(t)
    out = []
    for w, p in by.items():
        d = "YES" if p["YES"] >= p["NO"] else "NO"
        out.append({"wallet": w, "direction": d, "notional": p[d],
                    "opposite": p["NO" if d == "YES" else "YES"], "trades": p["trades"]})
    return out


def get_profile(conn, wallet, before_ts, wc, fetch, now):
    cached = db.get_wallet(conn, wallet)
    if cached and now - cached["fetched_ts"] < wc["profile_ttl_hours"] * 3600:
        return dict(cached), False
    prof = fetch(wallet, before_ts)
    db.upsert_wallet(conn, prof, now)
    return prof, True


def detect_wallets(conn, market_id, cfg, fetch, budget, now=None, fetch_track=None):
    """Return wallet alerts for one Polymarket market. `budget` is a one-item list of remaining lookups."""
    wc, platform = cfg["wallet"], "polymarket"
    now = now or time.time()
    recent = db.trades_between(conn, platform, market_id, now - 3 * 3600, now)
    if not recent:
        return []
    end = recent[-1]["ts"]
    window = [t for t in recent if t["ts"] > end - wc["window_minutes"] * 60]
    proven = db.proven_wallets(conn)
    min_proven = cfg["track"]["proven_min_position"]
    cands = [p for p in positions(window, wc) if p["notional"] >= wc["min_position"]
             or (p["wallet"] in proven and p["notional"] >= min_proven)]
    if not cands:
        return []
    base = load_baseline(conn, platform, market_id, end - wc["window_minutes"] * 60, cfg)
    if base.median_trade <= 0:
        return []
    market = dict(db.get_market(conn, platform, market_id) or {})
    snap = db.latest_snapshot(conn, platform, market_id)
    alerts = []
    for p in sorted(cands, key=lambda p: -p["notional"]):
        ratio = p["notional"] / base.median_trade
        if ratio < wc["min_position_vs_median"] and p["wallet"] not in proven:
            continue
        start = p["trades"][0]["ts"]
        cached = db.get_wallet(conn, p["wallet"])
        if not cached and budget[0] <= 0:
            continue
        try:
            prof, fetched = get_profile(conn, p["wallet"], start, wc, fetch, now)
        except Exception:
            continue
        budget[0] -= int(fetched)
        classes = classify(prof, start, wc)
        track = {}
        if fetch_track and (budget[0] > 0 or p["wallet"] in proven):
            try:
                row = db.get_wallet(conn, p["wallet"])
                stale = not (row and row["track_fetched_ts"])
                track = get_track(conn, p["wallet"], cfg, fetch_track, now)
                budget[0] -= int(stale)
            except Exception:
                track = {}
        if track.get("proven"):
            classes.insert(0, "PROVEN WALLET")
        prof["track"] = track
        if classes:
            alerts.append(_build_alert(conn, market_id, p, prof, classes, ratio, base, market, snap,
                                       recent, start, end, cfg))
    return alerts


def _build_alert(conn, market_id, p, prof, classes, ratio, base, market, snap, recent, start, end, cfg):
    wc, d = cfg["wallet"], p["direction"]
    yes_label, no_label = market.get("yes_label") or "YES", market.get("no_label") or "NO"
    d_label = yes_label if d == "YES" else no_label
    comp, why = {}, []

    first = prof.get("first_seen_ts")
    track = prof.get("track") or {}
    if track.get("strength") is not None:
        comp["track_record"] = track["strength"]
    if track:
        why.append(describe(track))
    newness = [NEWNESS[c] for c in classes if c in NEWNESS]
    if newness:
        comp["newness"] = max(newness)
    if "NEW WALLET" in classes:
        if start - first < 120:
            why.append("this position is the wallet's first observed Polymarket activity")
        else:
            why.append(f"first seen on Polymarket {ago(start - first)} before this position")
    if "REACTIVATED WALLET" in classes:
        why.append(f"previous trade {ago(start - prof['last_prior_trade_ts'])} before this position")
    if prof.get("markets_traded") is not None:
        why.append(f"{prof['markets_traded']} market(s) traded in its observable history (incl. this one)")

    comp["position"] = log_strength(ratio, wc["position_full_ratio"])
    why.append(f"position {money(p['notional'])} {d_label} = {ratio:.0f}x this market's median trade "
               f"({money(base.median_trade)}) — aggregate position vs single-trade size")

    share = p["notional"] / (p["notional"] + p["opposite"])
    comp["directional"] = clamp01((share - 0.5) / 0.5)
    why.append(f"{share * 100:.0f}% of this wallet's flow in the market favored {d_label}")

    val = prof.get("observable_value")
    if val:
        conc = min(p["notional"] / max(val, p["notional"]), 1.0)
        comp["capital_concentration"] = conc
        why.append(f"position ≈ {conc * 100:.0f}% of the wallet's observable open-position value "
                   f"({money(val)}) — observable capital may not be its full capital")

    before = [t for t in recent if t["ts"] < start]
    p0 = before[-1]["price"] if before else p["trades"][0]["price"]
    p1 = p["trades"][-1]["price"]
    move = (p1 - p0) * 100 * (1 if d == "YES" else -1)
    comp["price"] = clamp01(move / cfg["scaling"]["price_full_points"])
    why.append(f"{yes_label} probability {p0 * 100:.0f}% → {p1 * 100:.0f}% while it traded "
               f"({(p1 - p0) * 100:+.1f} pts)")

    if snap and snap["liquidity"]:
        r = p["notional"] / snap["liquidity"]
        comp["liquidity"] = clamp01(r / cfg["scaling"]["liquidity_full_ratio"])
        why.append(f"position = {r * 100:.1f}% of market order-book liquidity ({money(snap['liquidity'])})")

    weights = {k: w for k, w in wc["weights"].items() if k in comp}
    score = 100 * sum(comp[k] * w for k, w in weights.items()) / sum(weights.values())
    cls = classes[0]
    tier = "HIGH-SIGNIFICANCE" if score >= wc["high_threshold"] else "NOTABLE"
    severity = f"{tier} {cls.replace(' WALLET', '')}-WALLET ACTIVITY"

    strong = [k for k, v in comp.items() if v >= 0.5]
    conf_reasons = []
    if base.n_trades < cfg["min_baseline_trades"]:
        conf = "LOW"
        conf_reasons.append(f"market baseline thin ({base.n_trades} prior trades)")
    else:
        conf = "HIGH" if len(strong) >= 4 else "MEDIUM" if len(strong) >= 3 else "LOW"
        conf_reasons.append(f"{len(strong)} strong components ({', '.join(strong)})")
    conf_reasons.append("first seen = first observed activity, not wallet creation; funding not checked")

    ctx = []
    if p["opposite"] > 0:
        ctx.append(f"wallet also traded {money(p['opposite'])} the other way — could be hedging/market making")
    close_t = market.get("close_time")
    if close_t and 0 <= close_t - end <= cfg["near_close_minutes"] * 60:
        ctx.append("near market close — late positioning is common")
    ctx.append("benign explanations include a known trader using a new wallet, moved capital, "
               "arbitrage or reacting to public news")

    mw = db.last_alert(conn, "polymarket", market_id, d)
    notes = [f"wallet {p['wallet']} — {', '.join(classes)}",
             f"{len(p['trades'])} taker (aggressive) fill(s) over {ago(max(end - start, 60))}"]
    if mw and end - mw["ts"] < 3600:
        notes.append(f"market Whale Score for {d}: {mw['score']:.0f}/100 ({mw['severity']})")
    return {
        "kind": "wallet",
        "wallet": p["wallet"],
        "store_threshold": wc["store_threshold"],
        "color": "WALLET HIGH" if tier == "HIGH-SIGNIFICANCE" else "WALLET NOTABLE",
        "ts": end,
        "platform": "polymarket",
        "market_id": market_id,
        "title": market.get("title") or market_id,
        "direction": d,
        "score": round(score, 1),
        "severity": severity,
        "confidence": conf,
        "headline": f"🚨 {severity} — Score {score:.0f}/100",
        "evidence": {
            "direction_label": d_label,
            "detected": f"{money(p['notional'])} {d} position built by one wallet",
            "why": why,
            "notes": notes,
            "context": ctx,
            "confidence_reasons": conf_reasons,
            "signals": {k: round(v, 3) for k, v in comp.items()},
            "classes": classes,
            "dir_notional": p["notional"],
            "volume_text": None,
            "price_from": p0,
            "price_to": p1,
            "url": market.get("url"),
            "baseline": {"trades": base.n_trades, "hours": round(base.span_s / 3600, 1),
                         "median_trade": round(base.median_trade, 2)},
        },
    }
