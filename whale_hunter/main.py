"""Collector + detection loop: poll trades -> refresh metadata -> backfill if needed -> score -> alert."""
from __future__ import annotations

import logging
import time

from rich.logging import RichHandler

from . import alerts, db, maker, outcomes
from .collectors import kalshi, polymarket
from .config import load_config
from .score import LOOKBACK_EVAL_S, analyze_market
from .wallets import detect_wallets

log = logging.getLogger("whale_hunter")
# Overlap re-polls a little history each cycle; duplicates are dropped by trade_id.
PLATFORMS = {"kalshi": (kalshi, 30, 120), "polymarket": (polymarket, 120, 900)}  # mod, overlap, first-run lookback
MAX_BACKFILLS_PER_CYCLE = 10


def poll(conn, cfg):
    touched = {}
    for name, (mod, overlap, first) in PLATFORMS.items():
        last = float(db.get_state(conn, f"last_ts:{name}", time.time() - first))
        try:
            trades = mod.poll_trades(last - overlap, cfg["max_pages_per_poll"])
        except Exception as e:  # keep running through platform/API outages
            log.warning("%s poll failed: %s", name, e)
            continue
        new = db.insert_trades(conn, trades)
        if trades:
            db.set_state(conn, f"last_ts:{name}", max(last, max(t["ts"] for t in trades)))
        touched[name] = {t["market_id"] for t in new}
        conn.execute("INSERT INTO poll_log VALUES (?,?,?)", (time.time(), name, len(new)))
        conn.commit()
        log.info("%s: %d new trades across %d markets", name, len(new), len(touched[name]))
    return touched


def candidates(conn, platform, market_ids, cfg):
    """Markets whose last-15m flow clears the noise floor."""
    if not market_ids:
        return []
    rows = conn.execute(
        "SELECT market_id, SUM(notional) v FROM trades WHERE platform=? AND ts > ?"
        " GROUP BY market_id HAVING v >= ?",
        (platform, time.time() - LOOKBACK_EVAL_S - 900, cfg["min_window_notional"]),
    ).fetchall()
    return [r["market_id"] for r in rows if r["market_id"] in market_ids]


def refresh_metadata(conn, platform, market_ids, cfg):
    cutoff = time.time() - cfg["metadata_refresh_seconds"]
    stale = [m for m in market_ids
             if (db.get_market(conn, platform, m)["meta_updated_ts"] or 0) < cutoff]
    if not stale:
        return
    try:
        for m in PLATFORMS[platform][0].fetch_markets(stale):
            db.upsert_market(conn, m)
        conn.commit()
    except Exception as e:
        log.warning("%s metadata fetch failed: %s", platform, e)


def detect(conn, touched, cfg):
    new_ids, backfills = [], 0
    budget = [cfg["wallet"]["max_profiles_per_cycle"]]  # wallet profile API lookups left this cycle
    for platform, ids in touched.items():
        cands = candidates(conn, platform, ids, cfg)
        refresh_metadata(conn, platform, cands, cfg)
        for mid in cands:
            result = analyze_market(conn, platform, mid, cfg)
            if result and result.get("needs_backfill"):
                if backfills >= MAX_BACKFILLS_PER_CYCLE or db.get_market(conn, platform, mid)["backfilled"]:
                    continue
                backfills += 1
                try:
                    hist = PLATFORMS[platform][0].backfill(
                        mid, time.time() - cfg["baseline_days"] * 86400, cfg["backfill_max_pages"])
                    db.insert_trades(conn, hist)
                except Exception as e:
                    log.warning("backfill %s failed: %s", mid, e)
                conn.execute("UPDATE markets SET backfilled=1 WHERE platform=? AND market_id=?",
                             (platform, mid))
                conn.commit()
                result = analyze_market(conn, platform, mid, cfg)
            if result and not result.get("needs_backfill"):
                new_ids.append(alerts.handle(conn, result, cfg))
            if platform == "polymarket" and cfg["wallet"]["enabled"]:
                for wa in detect_wallets(conn, mid, cfg, polymarket.fetch_wallet_profile, budget,
                                         fetch_track=polymarket.fetch_closed_positions):
                    new_ids.append(alerts.handle(conn, wa, cfg))
        log.info("%s: evaluated %d candidate markets", platform, len(cands))
    return [i for i in new_ids if i], backfills


FETCH_MARKETS = {name: mod.fetch_markets for name, (mod, _, _) in PLATFORMS.items()}


def track_outcomes(conn, new_ids, cfg):
    opened = outcomes.open_paper_trades(conn, new_ids, cfg, FETCH_MARKETS)
    last = float(db.get_state(conn, "last_resolution_check", 0))
    if time.time() - last >= cfg["paper"]["resolution_check_minutes"] * 60 / 3:
        for platform, ids in outcomes.markets_to_resolve(conn, cfg).items():
            try:
                for m in FETCH_MARKETS[platform](ids):
                    db.upsert_market(conn, m)
                conn.commit()
            except Exception as e:
                log.warning("%s resolution check failed: %s", platform, e)
        db.set_state(conn, "last_resolution_check", time.time())
    maker.simulate(conn, cfg)
    return opened, outcomes.record_outcomes(conn)


def housekeeping(conn, cfg, batch=100_000):
    """Keep the database from filling the disk, a little each cycle so the loop stays responsive."""
    # 1) Strip raw JSON from old rows (it duplicated the normalized columns; ~75% of the file).
    cursor = int(db.get_state(conn, "slim_rowid", 0))
    top = conn.execute("SELECT MAX(rowid) FROM trades").fetchone()[0] or 0
    if cursor < top:
        conn.execute("UPDATE trades SET raw_json=NULL WHERE rowid > ? AND rowid <= ? AND raw_json IS NOT NULL",
                     (cursor, cursor + batch))
        db.set_state(conn, "slim_rowid", min(cursor + batch, top))
    # 2) Drop trades past the retention window. Rows are stored roughly in time order, so checking
    #    the oldest row is cheap and avoids scanning the table when there's nothing to delete.
    cutoff = time.time() - cfg["trades_retention_days"] * 86400
    oldest = conn.execute("SELECT ts FROM trades ORDER BY rowid LIMIT 1").fetchone()
    if oldest and oldest["ts"] < cutoff:
        conn.execute("DELETE FROM trades WHERE rowid IN (SELECT rowid FROM trades ORDER BY rowid LIMIT ?)"
                     " AND ts < ?", (batch // 2, cutoff))
    conn.execute("DELETE FROM poll_log WHERE ts < ?", (time.time() - 7 * 86400,))
    conn.commit()


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[RichHandler(show_path=False)])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    log.info("Whale Hunter running — db %s, polling every %ss", cfg["db_path"], cfg["poll_seconds"])
    while True:
        started = time.time()
        touched = poll(conn, cfg)
        new_ids, backfills = detect(conn, touched, cfg)
        opened, recorded = track_outcomes(conn, new_ids, cfg)
        db.set_state(conn, "last_cycle_ts", time.time())  # dashboard health indicator
        housekeeping(conn, cfg)
        log.info("cycle done in %.1fs — %d alerts stored, %d paper trades opened, %d outcomes recorded,"
                 " %d backfills", time.time() - started, len(new_ids), opened, recorded, backfills)
        time.sleep(max(0, cfg["poll_seconds"] - (time.time() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
