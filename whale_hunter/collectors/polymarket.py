"""Polymarket public data (Gamma for metadata, Data API for trades). Trades include proxy wallets."""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

from .common import chunks, fnum, get_json, log, parse_iso

PLATFORM = "polymarket"
GAMMA = "https://gamma-api.polymarket.com"
DATA = "https://data-api.polymarket.com"
MAX_OFFSET = 10_000  # Data API rejects deeper offsets


def _normalize_trade(t):
    # "YES" means outcome index 0 (often literally "Yes", sometimes a team/candidate name).
    idx, price, size = t.get("outcomeIndex", 0), float(t["price"]), float(t["size"])
    yes_side = (idx == 0) == (t["side"] == "BUY")
    key = "|".join(str(t.get(k)) for k in
                   ("transactionHash", "asset", "proxyWallet", "side", "size", "price", "timestamp"))
    return {
        "trade_id": "p:" + hashlib.sha1(key.encode()).hexdigest(),
        "platform": PLATFORM,
        "market_id": t["conditionId"],
        "ts": float(t["timestamp"]),
        "price": price if idx == 0 else 1 - price,
        "size": size,
        "notional": size * price,
        "direction": "YES" if yes_side else "NO",
        "taker": True,  # Data API /trades returns taker fills by default
        "wallet": t.get("proxyWallet"),
        "raw": t,
    }


def _page_trades(params, since_ts, max_pages):
    out, stamp = [], int(time.time())
    max_pages = min(max_pages, MAX_OFFSET // 1000 + 1)
    for page in range(max_pages):
        # The CDN caches identical URLs for 5 minutes; a per-poll param gets fresh data.
        data = get_json(f"{DATA}/trades", dict(params, limit=1000, offset=page * 1000, _t=stamp))
        if not data:
            return out
        out.extend(_normalize_trade(t) for t in data if t["timestamp"] >= since_ts)
        if data[-1]["timestamp"] < since_ts:
            return out
    if not params:  # backfills are capped on purpose
        log.warning("polymarket: hit page cap (%d) - some trades may be missed", max_pages)
    return out


def poll_trades(since_ts, max_pages=15):
    return _page_trades({}, since_ts, max_pages)


def backfill(market_id, since_ts, max_pages=5):
    return _page_trades({"market": market_id}, since_ts, max_pages)


def _resolution(m, prices):
    """YES/NO once a closed market's outcome prices have settled to 1/0."""
    if not m.get("closed") or len(prices) < 2:
        return None
    p0 = fnum(prices[0])
    return "YES" if p0 is not None and p0 >= 0.99 else "NO" if p0 is not None and p0 <= 0.01 else None


def fetch_markets(market_ids):
    now = time.time()
    out = []
    for batch in chunks(market_ids, 20):
        data = get_json(f"{GAMMA}/markets", [("condition_ids", c) for c in batch])
        # Gamma omits closed markets unless asked; resolution checks need them.
        found = {m["conditionId"] for m in data}
        missing = [c for c in batch if c not in found]
        if missing:
            data += get_json(f"{GAMMA}/markets", [("condition_ids", c) for c in missing] + [("closed", "true")])
        for m in data:
            outcomes = json.loads(m.get("outcomes") or '["Yes","No"]')
            prices = json.loads(m.get("outcomePrices") or "[]")
            events = m.get("events") or [{}]
            out.append({
                "platform": PLATFORM,
                "market_id": m["conditionId"],
                "event_id": events[0].get("id"),
                "title": m.get("question"),
                "yes_label": outcomes[0] if outcomes else "Yes",
                "no_label": outcomes[1] if len(outcomes) > 1 else "No",
                "url": f"https://polymarket.com/event/{events[0].get('slug') or m.get('slug')}",
                "status": "closed" if m.get("closed") else "active",
                "open_time": parse_iso(m.get("startDate")),
                "close_time": parse_iso(m.get("endDate")),
                "price": fnum(prices[0]) if prices else fnum(m.get("lastTradePrice")),
                "bid": fnum(m.get("bestBid")),
                "ask": fnum(m.get("bestAsk")),
                "liquidity": fnum(m.get("liquidityNum")),
                "liquidity_kind": "order book",
                "volume_24h": fnum(m.get("volume24hr")),
                "open_interest": None,
                "result": _resolution(m, prices),
                "ts": now,
                "raw": m,
            })
    return out


def fetch_wallet_profile(wallet, before_ts):
    """Observable history for one proxy wallet. 'first_seen' is first Polymarket activity, not creation."""
    calls = [
        (f"{DATA}/activity", {"user": wallet, "limit": 1, "sortDirection": "ASC"}),
        (f"{DATA}/activity", {"user": wallet, "limit": 1, "type": "TRADE", "end": int(before_ts) - 1}),
        (f"{DATA}/traded", {"user": wallet}),
        (f"{DATA}/value", {"user": wallet}),
    ]
    with ThreadPoolExecutor(4) as pool:
        first, prior, traded, value = pool.map(lambda c: get_json(*c), calls)
    return {
        "wallet": wallet,
        "first_seen_ts": float(first[0]["timestamp"]) if first else None,
        "last_prior_trade_ts": float(prior[0]["timestamp"]) if prior else None,
        "markets_traded": int(traded.get("traded", 0)) if isinstance(traded, dict) else None,
        "observable_value": fnum(value[0].get("value")) if value else None,
    }


def fetch_closed_positions(wallet, max_positions=200):
    """Most recent closed positions (default API order is by PnL, which would bias a track record)."""
    out = []
    for offset in range(0, max_positions, 50):  # sequential: this endpoint rate-limits aggressively
        page = get_json(f"{DATA}/closed-positions", {
            "user": wallet, "limit": 50, "offset": offset, "sortBy": "TIMESTAMP", "sortDirection": "DESC"})
        out.extend(page)
        if len(page) < 50:
            break
        time.sleep(0.2)
    return out


def fetch_leaderboard(period="MONTH", order_by="PNL", limit=100):
    out = []
    for off in range(0, limit, 50):
        page = get_json(f"{DATA}/v1/leaderboard",
                        {"timePeriod": period, "orderBy": order_by, "limit": 50, "offset": off})
        out.extend(page)
        if len(page) < 50:
            break
    return out[:limit]
