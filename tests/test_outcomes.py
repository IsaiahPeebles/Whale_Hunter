from whale_hunter import db, outcomes
from whale_hunter.config import load_config
from whale_hunter.track import summarize

NOW = 1_800_000_000.0


def _closed(n, avg, bought, pnl):
    return [{"avgPrice": avg, "totalBought": bought, "realizedPnl": pnl} for _ in range(n)]


def test_favorite_buyer_with_high_win_rate_but_losses_is_not_proven():
    tc = load_config()["track"]
    # 98 tiny wins buying 99c favorites, 2 full losses -> net negative
    t = summarize(_closed(98, 0.99, 1000, 10) + _closed(2, 0.99, 1000, -990), tc)
    assert t["wins"] == 98 and t["pnl"] < 0
    assert t["strength"] == 0 and not t["proven"]


def test_profitable_wallet_with_enough_sample_is_proven():
    tc = load_config()["track"]
    t = summarize(_closed(40, 0.4, 1000, 400) + _closed(20, 0.4, 1000, -400), tc)  # +33% ROI
    assert t["proven"] and t["strength"] > 0.5


def test_small_sample_is_unknown_not_bad():
    t = summarize(_closed(5, 0.4, 1000, 600), load_config()["track"])
    assert t["strength"] is None and not t["proven"]


def _alert(conn, direction="YES", score=80, kind="market"):
    db.set_state(conn, "last_ts:polymarket", NOW + 2 * 86400)
    return db.insert_alert(conn, {"ts": NOW, "detected_ts": NOW, "platform": "polymarket",
                                  "market_id": "M1", "title": "t", "direction": direction, "score": score,
                                  "severity": "WHALE ACTIVITY", "confidence": "HIGH", "headline": "h",
                                  "evidence": {}, "kind": kind})


def _trades(conn, path):
    db.insert_trades(conn, [{"trade_id": f"x{i}", "platform": "polymarket", "market_id": "M1", "ts": ts,
                             "price": p, "size": 1, "notional": 1, "direction": "YES", "taker": True}
                            for i, (ts, p) in enumerate(path)])


def test_paper_trade_pays_ask_and_spread_and_tracks_moves():
    cfg = load_config()
    conn = db.connect(":memory:")
    _trades(conn, [(NOW - 10, 0.40), (NOW + 3000, 0.50), (NOW + 20000, 0.60)])
    aid = _alert(conn)
    quote = lambda ids: [{"platform": "polymarket", "market_id": "M1", "bid": 0.39, "ask": 0.41, "ts": NOW}]
    assert outcomes.open_paper_trades(conn, [aid], cfg, {"polymarket": quote}, now=NOW) == 1
    outcomes.record_outcomes(conn, now=NOW + 2 * 86400)
    [row] = outcomes.performance(conn)
    assert round(row["move"][3600], 1) == 10.0          # 40 -> 50 in YES direction
    # entry = ask 0.41 + 0.01 slippage; 6h exit at 0.60 minus half-spread 0.01
    assert round(row["ret"][21600], 4) == round((0.60 - 0.01) / 0.42 - 1, 4)


def test_no_direction_and_resolution_payout():
    cfg = load_config()
    conn = db.connect(":memory:")
    _trades(conn, [(NOW - 10, 0.70)])
    db.upsert_market(conn, {"platform": "polymarket", "market_id": "M1", "result": "NO",
                            "close_time": NOW + 100, "ts": NOW})
    aid = _alert(conn, direction="NO")
    quote = lambda ids: [{"platform": "polymarket", "market_id": "M1", "bid": 0.69, "ask": 0.71, "ts": NOW}]
    outcomes.open_paper_trades(conn, [aid], cfg, {"polymarket": quote}, now=NOW)
    outcomes.record_outcomes(conn, now=NOW + 2 * 86400)
    [row] = outcomes.performance(conn)
    # NO ask = 1 - YES bid = 0.31, +0.01 slippage; resolves NO -> pays 1
    assert round(row["ret"][-1], 4) == round(1 / 0.32 - 1, 4)
    assert round(row["move"][86400], 1) == 70.0  # NO went from 30% to 100%


def test_duplicate_paper_trades_are_skipped():
    cfg = load_config()
    conn = db.connect(":memory:")
    a1, a2 = _alert(conn), _alert(conn, score=95)
    quote = lambda ids: [{"platform": "polymarket", "market_id": "M1", "bid": 0.39, "ask": 0.41, "ts": NOW}]
    assert outcomes.open_paper_trades(conn, [a1, a2], cfg, {"polymarket": quote}, now=NOW) == 1
