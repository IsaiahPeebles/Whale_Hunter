import random

from whale_hunter import db
from whale_hunter.config import load_config
from whale_hunter.score import analyze_market

NOW = 1_800_000_000.0


def _trade(i, ts, notional, direction, price, market="M1"):
    return {"trade_id": f"t{market}{i}", "platform": "polymarket", "market_id": market, "ts": ts,
            "price": price, "size": notional / price, "notional": notional, "direction": direction,
            "taker": True, "wallet": f"0xw{i % 40}", "raw": None}


def _setup(baseline_size, n_base=400):
    """Two days of balanced background trading around 40%."""
    rnd = random.Random(1)
    conn = db.connect(":memory:")
    trades = []
    for i in range(n_base):
        ts = NOW - 2 * 86400 + i * (2 * 86400 - 1800) / n_base
        trades.append(_trade(i, ts, baseline_size * rnd.uniform(0.5, 1.5),
                             rnd.choice(["YES", "NO"]), 0.40 + rnd.uniform(-0.01, 0.01)))
    db.insert_trades(conn, trades)
    db.upsert_market(conn, {"platform": "polymarket", "market_id": "M1", "title": "Will X happen?",
                            "yes_label": "Yes", "no_label": "No", "liquidity": 120_000,
                            "liquidity_kind": "order book", "ts": NOW})
    return conn


def test_split_whale_burst_scores_high():
    conn = _setup(baseline_size=250)
    # 10 x $5k YES trades in 4 minutes walking the price 40% -> 52% (CONTEXT §12 example)
    burst = [_trade(1000 + i, NOW - 240 + i * 24, 5000, "YES", 0.41 + i * 0.012) for i in range(10)]
    db.insert_trades(conn, burst)
    a = analyze_market(conn, "polymarket", "M1", load_config(), now=NOW)
    assert a["direction"] == "YES"
    assert a["score"] >= 75, a
    why = " ".join(a["evidence"]["why"])
    assert "normal 5-minute volume" in why or "normal 15-minute volume" in why
    assert "40% → 52%" in why
    assert "10 YES trades" in why


def test_single_trade_in_deep_market_scores_low():
    conn = _setup(baseline_size=3000, n_base=3000)  # busy market
    db.insert_trades(conn, [_trade(9000, NOW - 30, 15000, "YES", 0.405)])
    a = analyze_market(conn, "polymarket", "M1", load_config(), now=NOW)
    assert a["score"] < 60, a


def test_insufficient_history_requests_backfill():
    conn = db.connect(":memory:")
    db.insert_trades(conn, [_trade(i, NOW - 60 + i, 5000, "YES", 0.5) for i in range(3)])
    assert analyze_market(conn, "polymarket", "M1", load_config(), now=NOW) == {"needs_backfill": True}
