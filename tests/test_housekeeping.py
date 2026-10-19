import time

from whale_hunter import db
from whale_hunter.config import load_config
from whale_hunter.main import housekeeping


def test_strips_raw_json_and_drops_expired_trades():
    cfg = load_config()
    conn = db.connect(":memory:")
    now = time.time()
    old, recent = now - 30 * 86400, now - 3600
    for i, ts in enumerate([old, old, recent, recent]):
        conn.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (f"t{i}", "kalshi", "M", ts, 0.5, 1, 1, "YES", 1, None, '{"big": "blob"}'))
    conn.commit()
    housekeeping(conn, cfg)
    rows = conn.execute("SELECT ts, raw_json FROM trades").fetchall()
    assert len(rows) == 2 and all(r["ts"] == recent for r in rows)
    assert all(r["raw_json"] is None for r in rows)


def test_new_trades_store_no_raw_json():
    conn = db.connect(":memory:")
    db.insert_trades(conn, [{"trade_id": "x", "platform": "kalshi", "market_id": "M", "ts": 1.0, "price": 0.5,
                             "size": 1, "notional": 1, "direction": "YES", "taker": True, "raw": {"a": 1}}])
    assert conn.execute("SELECT raw_json FROM trades").fetchone()[0] is None
