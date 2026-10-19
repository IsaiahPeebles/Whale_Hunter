import random

from whale_hunter import db
from whale_hunter.config import load_config
from whale_hunter.wallets import detect_wallets

NOW = 1_800_000_000.0
DAY = 86400


def _trade(i, ts, notional, direction, price, wallet):
    return {"trade_id": f"w{i}", "platform": "polymarket", "market_id": "M1", "ts": ts, "price": price,
            "size": notional / price, "notional": notional, "direction": direction, "taker": True,
            "wallet": wallet, "raw": None}


def _conn():
    rnd = random.Random(2)
    conn = db.connect(":memory:")
    db.insert_trades(conn, [
        _trade(i, NOW - 2 * DAY + i * 400, 250 * rnd.uniform(0.5, 1.5), rnd.choice(["YES", "NO"]),
               0.34 + rnd.uniform(-0.01, 0.01), f"0xbg{i % 50}")
        for i in range(400)])
    db.upsert_market(conn, {"platform": "polymarket", "market_id": "M1", "title": "Will X happen?",
                            "yes_label": "Yes", "no_label": "No", "liquidity": 300_000,
                            "liquidity_kind": "order book", "ts": NOW})
    return conn


def _whale(conn, wallet, total=180_000, n=6):
    db.insert_trades(conn, [_trade(9000 + i, NOW - 600 + i * 60, total / n, "YES", 0.35 + i * 0.012, wallet)
                            for i in range(n)])


def _profile(first_seen_ago, markets, last_prior_ago=None, value=200_000):
    def fetch(wallet, before):
        return {"wallet": wallet, "first_seen_ts": NOW - first_seen_ago, "markets_traded": markets,
                "last_prior_trade_ts": None if last_prior_ago is None else NOW - last_prior_ago,
                "observable_value": value}
    return fetch


def test_new_wallet_large_position_is_high_significance():
    conn = _conn()
    _whale(conn, "0xnew")
    [a] = detect_wallets(conn, "M1", load_config(), _profile(3 * 3600, 1), [5], now=NOW)
    assert a["kind"] == "wallet" and a["direction"] == "YES"
    assert a["severity"] == "HIGH-SIGNIFICANCE NEW-WALLET ACTIVITY", a
    why = " ".join(a["evidence"]["why"])
    assert "first seen on Polymarket" in why and "median trade" in why
    assert "insider" not in str(a).lower()


def test_reactivated_wallet_is_flagged():
    conn = _conn()
    _whale(conn, "0xold")
    [a] = detect_wallets(conn, "M1", load_config(), _profile(400 * DAY, 30, last_prior_ago=143 * DAY),
                         [5], now=NOW)
    assert "REACTIVATED WALLET" in a["evidence"]["classes"]


def test_established_wallet_produces_no_wallet_alert():
    conn = _conn()
    _whale(conn, "0xpro")
    assert detect_wallets(conn, "M1", load_config(), _profile(400 * DAY, 300, last_prior_ago=DAY),
                          [5], now=NOW) == []


def test_small_position_ignored_and_no_lookup():
    conn = _conn()
    _whale(conn, "0xsmall", total=3000)
    calls = []
    detect_wallets(conn, "M1", load_config(), lambda w, b: calls.append(w), [5], now=NOW)
    assert calls == []


def test_profiles_are_cached():
    conn = _conn()
    _whale(conn, "0xnew")
    calls = []
    fetch = _profile(3 * 3600, 1)
    counting = lambda w, b: (calls.append(w), fetch(w, b))[1]
    cfg = load_config()
    detect_wallets(conn, "M1", cfg, counting, [5], now=NOW)
    detect_wallets(conn, "M1", cfg, counting, [5], now=NOW + 60)
    assert calls == ["0xnew"]
