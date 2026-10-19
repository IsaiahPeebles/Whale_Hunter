"""Relative-activity signals for one market (CONTEXT §7-13). Each signal: strength 0..1 + explanation."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .baseline import Baseline


@dataclass
class Signal:
    strength: float
    text: str


@dataclass
class Event:
    window_min: int
    direction: str               # YES | NO
    start: float
    end: float
    n_trades: int
    dir_notional: float
    total_notional: float
    price_from: float | None
    price_to: float | None
    signals: dict = field(default_factory=dict)  # name -> Signal (missing = not evaluable)
    notes: list = field(default_factory=list)    # observed context, not scored


def log_strength(ratio, full):
    if not ratio or ratio <= 1:
        return 0.0
    return min(math.log(ratio) / math.log(full), 1.0)


def clamp01(x):
    return max(0.0, min(1.0, x))


def money(x):
    if x >= 1e6:
        return f"${x / 1e6:.2f}M"
    if x >= 1e4:
        return f"${x / 1e3:.1f}k"
    return f"${x:,.0f}"


def pct(q):
    if q is None:
        return "no history"
    return "above all prior observations" if q >= 1 else f"{q * 100:.1f}th percentile"


def span_text(seconds):
    h = seconds / 3600
    return f"{h / 24:.1f} days" if h >= 48 else f"{h:.1f} hours"


def evaluate_window(recent, base: Baseline, end, window_min, liquidity, liquidity_kind,
                    accumulation_trades, labels, sc) -> Event | None:
    w = window_min * 60
    win = [t for t in recent if t["ts"] > end - w]
    if not win:
        return None
    flow = defaultdict(float)
    for t in win:
        flow[t["direction"]] += t["notional"]
    d = "YES" if flow["YES"] >= flow["NO"] else "NO"
    dtrades = [t for t in win if t["direction"] == d]
    dir_notional, total = flow[d], flow["YES"] + flow["NO"]
    before = [t for t in recent if t["ts"] <= end - w]
    p0 = before[-1]["price"] if before else (base.last_price if base.last_price is not None
                                              else win[0]["price"])
    p1 = win[-1]["price"]
    ev = Event(window_min, d, win[0]["ts"], end, len(win), dir_notional, total, p0, p1)
    yes_label, no_label = labels
    d_label = yes_label if d == "YES" else no_label
    s = ev.signals

    # Trade size anomaly: largest single directional trade vs this market's median trade.
    big = max(t["notional"] for t in dtrades)
    if base.median_trade > 0:
        r = big / base.median_trade
        s["trade_size"] = Signal(log_strength(r, sc["trade_size_full_ratio"]),
                                 f"largest single trade {money(big)} = {r:.1f}x median trade "
                                 f"({money(base.median_trade)}), {pct(base.size_percentile(big))}")

    # Volume anomaly vs normal volume for a window of this length.
    bs = {1: 60, 5: 300, 15: 900}.get(window_min, 300)
    normal = base.avg_volume.get(bs, 0)
    if normal > 0:
        r = total / normal
        text = f"{r:.1f}x normal {window_min}-minute volume ({pct(base.volume_percentile(bs, total))})"
        if total > base.max_volume(bs) and base.span_s >= 6 * 3600:
            text += f"; largest {window_min}-minute volume in {span_text(base.span_s)} observed"
        s["volume"] = Signal(log_strength(r, sc["volume_full_ratio"]), text)

    # Clustering: many same-direction trades treated as one event (CONTEXT §12).
    if len(dtrades) >= 2 and base.p99_trade > 0:
        r = dir_notional / base.p99_trade
        s["clustering"] = Signal(log_strength(r, sc["cluster_full_ratio"]),
                                 f"{len(dtrades)} {d} trades totalling {money(dir_notional)} in "
                                 f"{window_min}m ({r:.1f}x the 99th-percentile single trade)")
    else:
        s["clustering"] = Signal(0.0, "")

    # Price impact, measured in the event direction (probability points).
    move = (p1 - p0) * 100 * (1 if d == "YES" else -1)
    s["price"] = Signal(clamp01(move / sc["price_full_points"]),
                        f"{yes_label} probability {p0 * 100:.0f}% → {p1 * 100:.0f}% "
                        f"({(p1 - p0) * 100:+.1f} pts)")

    # Liquidity-adjusted size (CONTEXT §10).
    if liquidity:
        r = dir_notional / liquidity
        s["liquidity"] = Signal(clamp01(r / sc["liquidity_full_ratio"]),
                                f"directional flow = {r * 100:.1f}% of market {liquidity_kind} "
                                f"({money(liquidity)})")

    # Directional aggression: share of taker flow on one side; discounted for tiny samples.
    taker = [t for t in win if t["taker"]]
    taker_total = sum(t["notional"] for t in taker)
    if taker_total > 0:
        share = sum(t["notional"] for t in taker if t["direction"] == d) / taker_total
        s["aggression"] = Signal(clamp01((share - 0.5) / 0.5) * min(1.0, len(taker) / 3),
                                 f"{share * 100:.0f}% of aggressive (taker) flow favored {d_label}")

    # Sustained accumulation over the longer horizon (CONTEXT §13).
    hour_normal = base.avg_volume.get(3600, 0)
    if accumulation_trades and hour_normal > 0:
        net = sum(t["notional"] * (1 if t["direction"] == d else -1) for t in accumulation_trades)
        if net > 0:
            r = net / hour_normal
            s["accumulation"] = Signal(log_strength(r, sc["accumulation_full_ratio"]),
                                       f"net {d_label} accumulation {money(net)} over the last hour "
                                       f"({r:.1f}x normal hourly volume)")

    # Participant concentration where attribution exists (Polymarket wallets) — context only.
    wallets = defaultdict(float)
    for t in dtrades:
        if t.get("wallet"):
            wallets[t["wallet"]] += t["notional"]
    if wallets:
        top_w, top_v = max(wallets.items(), key=lambda kv: kv[1])
        ev.notes.append(f"{len(wallets)} wallet(s) behind {d} flow; top wallet {top_w[:10]}… "
                        f"= {top_v / dir_notional * 100:.0f}% ({money(top_v)})")
    return ev
