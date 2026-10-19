from whale_hunter import db
from whale_hunter.config import load_config
from whale_hunter.outcomes import paper_return
from whale_hunter.strategies import evaluate, start_ts


def test_settlement_return_includes_entry_fee():
    # Kalshi: $100 at 60c buys 166.67 contracts; fee = 166.67 * 0.07 * 0.6 * 0.4 = $2.80
    assert round(paper_return(0.60, 1.0, 0.07, True) * 100, 2) == round(100 / 0.6 - 100 - 2.80, 2)
    assert round(paper_return(0.60, 0.0, 0.07, True) * 100, 2) == -102.80


def test_early_exit_pays_fee_twice():
    held = paper_return(0.60, 0.70, 0.07, True)
    sold = paper_return(0.60, 0.70, 0.07, False)
    assert sold < held
    assert round((held - sold) * 100, 4) == round(100 / 0.6 * 0.07 * 0.7 * 0.3, 4)


def _bet(conn, i, ts, platform, score, won, cls=None, mid=0.5):
    evidence = {"classes": [cls]} if cls else {}
    aid = db.insert_alert(conn, {"ts": ts, "detected_ts": ts, "platform": platform, "market_id": f"M{i}",
                                 "title": "t", "direction": "YES", "score": score, "severity": "s",
                                 "confidence": "HIGH", "headline": "h", "evidence": evidence,
                                 "kind": "wallet" if cls else "market"})
    conn.execute("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?)",
                 (aid, ts, platform, f"M{i}", "YES", mid, mid + 0.02, 0.01, 100))
    db.upsert_market(conn, {"platform": platform, "market_id": f"M{i}", "result": "YES" if won else "NO", "ts": ts})


def test_rules_match_and_only_count_bets_after_start():
    cfg = load_config()
    conn = db.connect(":memory:")
    t0 = start_ts(cfg)
    _bet(conn, 1, t0 - 60, "polymarket", 95, True)        # before start: ignored
    _bet(conn, 2, t0 + 60, "polymarket", 80, True)
    _bet(conn, 3, t0 + 60, "kalshi", 92, False)
    _bet(conn, 4, t0 + 60, "polymarket", 62, True, cls="PROVEN WALLET")
    by = {s["name"]: s for s in evaluate(conn, cfg)}
    assert by["All alerts (control)"]["bets"] == 3
    assert by["Polymarket, score 75+"]["bets"] == 1 and by["Polymarket, score 75+"]["win"] == 1.0
    assert by["Score 90+"]["bets"] == 1 and by["Score 90+"]["win"] == 0.0
    assert by["Proven wallets"]["bets"] == 1


def test_price_band_and_per_rule_start():
    cfg = load_config()
    cfg["strategies"]["rules"] = [{"name": "late, mid-priced", "start": "2030-01-01 00:00",
                                   "min_price": 0.30, "max_price": 0.70}]
    conn = db.connect(":memory:")
    t1 = start_ts(cfg, cfg["strategies"]["rules"][0])
    _bet(conn, 1, t1 - 60, "polymarket", 80, True)            # before this rule's start: ignored
    _bet(conn, 2, t1 + 60, "polymarket", 80, True, mid=0.50)
    _bet(conn, 3, t1 + 60, "polymarket", 80, True, mid=0.80)  # outside the price band
    _bet(conn, 4, t1 + 60, "polymarket", 80, True, mid=0.25)
    assert evaluate(conn, cfg)[0]["bets"] == 1


def test_maker_fill_needs_a_trade_through_our_price():
    from whale_hunter.maker import first_fill
    conn = db.connect(":memory:")
    db.insert_trades(conn, [
        {"trade_id": "a", "platform": "kalshi", "market_id": "M", "ts": 10, "price": 0.40, "size": 1,
         "notional": 1, "direction": "NO", "taker": True},   # someone sells YES at exactly our 40c bid
        {"trade_id": "b", "platform": "kalshi", "market_id": "M", "ts": 20, "price": 0.39, "size": 1,
         "notional": 1, "direction": "NO", "taker": True},   # ...then through it at 39c
        {"trade_id": "c", "platform": "kalshi", "market_id": "M", "ts": 30, "price": 0.70, "size": 1,
         "notional": 1, "direction": "YES", "taker": True},  # YES buyer at 70c = NO seller at 30c
    ])
    assert first_fill(conn, "kalshi", "M", "YES", 0.40, 0, 100) == 20   # touch at 40c doesn't count
    assert first_fill(conn, "kalshi", "M", "YES", 0.40, 0, 15) is None
    assert first_fill(conn, "kalshi", "M", "NO", 0.31, 0, 100) == 30    # NO bid 31c, NO traded at 30c
    assert first_fill(conn, "kalshi", "M", "NO", 0.30, 0, 100) is None
