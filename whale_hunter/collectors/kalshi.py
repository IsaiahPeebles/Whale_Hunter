"""Kalshi public market data. Kalshi trades carry no participant identity."""
from __future__ import annotations

import time

from .common import chunks, fnum, get_json, log, parse_iso

PLATFORM = "kalshi"
BASE = "https://api.elections.kalshi.com/trade-api/v2"


def _normalize_trade(t):
    yes_price = fnum(t["yes_price_dollars"])
    count = fnum(t["count_fp"]) or 0.0
    direction = "YES" if t["taker_side"] == "yes" else "NO"
    paid = yes_price if direction == "YES" else fnum(t["no_price_dollars"])
    return {
        "trade_id": f"k:{t['trade_id']}",
        "platform": PLATFORM,
        "market_id": t["ticker"],
        "ts": parse_iso(t["created_time"]),
        "price": yes_price,
        "size": count,
        "notional": count * paid,
        "direction": direction,
        "taker": True,
        "wallet": None,
        "raw": t,
    }


def _page_trades(params, since_ts, max_pages):
    out, cursor = [], None
    for _ in range(max_pages):
        p = dict(params, limit=1000, min_ts=int(since_ts))
        if cursor:
            p["cursor"] = cursor
        data = get_json(f"{BASE}/markets/trades", p)
        out.extend(_normalize_trade(t) for t in data.get("trades", []))
        cursor = data.get("cursor")
        if not cursor or not data.get("trades"):
            return out
    if not params:  # backfills are capped on purpose
        log.warning("kalshi: hit page cap (%d) - some trades may be missed", max_pages)
    return out


def poll_trades(since_ts, max_pages=15):
    # Skip multivariate parlay markets: they have no meaningful per-market baseline.
    return [t for t in _page_trades({}, since_ts, max_pages) if not t["market_id"].startswith("KXMVE")]


def backfill(market_id, since_ts, max_pages=5):
    return _page_trades({"ticker": market_id}, since_ts, max_pages)


def fetch_markets(market_ids):
    now = time.time()
    out = []
    for batch in chunks(market_ids, 100):
        data = get_json(f"{BASE}/markets", {"tickers": ",".join(batch)})
        for m in data.get("markets", []):
            bid, ask = fnum(m.get("yes_bid_dollars")), fnum(m.get("yes_ask_dollars"))
            price = (bid + ask) / 2 if bid and ask else fnum(m.get("last_price_dollars"))
            oi = fnum(m.get("open_interest_fp"))
            out.append({
                "platform": PLATFORM,
                "market_id": m["ticker"],
                "event_id": m.get("event_ticker"),
                "title": m.get("title"),
                "yes_label": m.get("yes_sub_title") or "Yes",
                "no_label": "No",
                "url": f"https://kalshi.com/markets/{m.get('event_ticker', '').split('-')[0].lower()}",
                "status": m.get("status"),
                "open_time": parse_iso(m.get("open_time")),
                "close_time": parse_iso(m.get("close_time")),
                "price": price,
                "bid": bid,
                "ask": ask,
                # Kalshi exposes no liquidity figure; open-interest notional is the closest proxy.
                "liquidity": oi * price if oi and price else None,
                "liquidity_kind": "open interest",
                "volume_24h": fnum(m.get("volume_24h_fp")),
                "open_interest": oi,
                "result": (m.get("result") or "").upper() if m.get("result") in ("yes", "no") else None,
                "ts": now,
                "raw": m,
            })
    return out
