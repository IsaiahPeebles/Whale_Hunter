"""Wallet track records: did this wallet's recent closed positions make money? (CONTEXT §24)

Seed a watchlist:  python -m whale_hunter.track seed --period MONTH --top 200
Score one wallet:  python -m whale_hunter.track 0xabc...
"""
from __future__ import annotations

import argparse
import time

from . import db
from .config import load_config
from .detect import clamp01, money


def summarize(closed, tc):
    """Shrunk ROI + win rate. Small samples are 'unknown' (strength None), never treated as poor."""
    n = len(closed)
    invested = sum(c["totalBought"] * c["avgPrice"] for c in closed)
    pnl = sum(c["realizedPnl"] for c in closed)
    wins = sum(1 for c in closed if c["realizedPnl"] > 0)
    t = {"n": n, "wins": wins, "pnl": pnl, "invested": invested, "strength": None, "proven": False}
    if n < tc["min_sample"] or invested < tc["min_invested"]:
        return t
    roi = pnl / invested * n / (n + tc["roi_shrink"])
    win = (wins + tc["win_prior"] / 2) / (n + tc["win_prior"])
    # Profit drives strength; a high win rate from buying 99c favorites is not skill on its own.
    t["strength"] = 0.0 if roi <= 0 else \
        0.8 * clamp01(roi / tc["roi_full"]) + 0.2 * clamp01((win - 0.5) / 0.2)
    t["proven"] = roi >= tc["proven_min_roi"] and t["strength"] >= tc["proven_min_strength"]
    t["roi_shrunk"], t["win_shrunk"] = roi, win
    return t


def describe(t):
    if t.get("n") is None:
        return "track record not fetched"
    if t["strength"] is None:
        return f"track record unknown ({t['n']} recent closed positions; too few to judge)"
    roi = t["pnl"] / t["invested"] if t["invested"] else 0
    return (f"recent track record: {t['n']} closed positions, {t['wins'] / t['n'] * 100:.0f}% profitable, "
            f"{money(t['pnl']) if t['pnl'] >= 0 else '-' + money(-t['pnl'])} realized "
            f"({roi * 100:+.1f}% on {money(t['invested'])})")


def get_track(conn, wallet, cfg, fetch, now=None, username=None):
    """Cached track record for a wallet as a dict (n, wins, pnl, invested, strength, proven)."""
    now = now or time.time()
    row = db.get_wallet(conn, wallet)
    if row and row["track_fetched_ts"] and now - row["track_fetched_ts"] < cfg["track"]["ttl_hours"] * 3600:
        return {"n": row["track_n"], "wins": row["track_wins"], "pnl": row["track_pnl"],
                "invested": row["track_invested"], "strength": row["track_strength"],
                "proven": bool(row["proven"])}
    t = summarize(fetch(wallet, cfg["track"]["max_positions"]), cfg["track"])
    db.upsert_track(conn, wallet, t, now, username)
    return t


def seed(period, top, order_by="PNL"):
    from .collectors import polymarket
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    board = polymarket.fetch_leaderboard(period, order_by, top)
    print(f"Scoring {len(board)} {period} leaderboard wallets on their recent closed positions…")
    rows = []
    for i, r in enumerate(board, 1):
        try:  # one wallet at a time (4 parallel pages each) to stay under the API rate limit
            c = polymarket.fetch_closed_positions(r["proxyWallet"], cfg["track"]["max_positions"])
        except Exception as e:
            print(f"  skip {r['proxyWallet']}: {e}")
            continue
        if i % 25 == 0:
            print(f"  {i}/{len(board)}")
        t = summarize(c, cfg["track"])
        db.upsert_track(conn, r["proxyWallet"], t, time.time(), r.get("userName"))
        rows.append((r, t))
    proven = [(r, t) for r, t in rows if t["proven"]]
    print(f"{len(proven)} PROVEN wallets (of {len(rows)}; leaderboard rank alone is not enough):")
    for r, t in sorted(proven, key=lambda rt: -rt[1]["strength"]):
        print(f"  {r['proxyWallet']}  {(r.get('userName') or '')[:18]:18}  strength {t['strength']:.2f}  {describe(t)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", help="'seed' or a wallet address")
    ap.add_argument("--period", default="MONTH", choices=["DAY", "WEEK", "MONTH", "ALL"])
    ap.add_argument("--top", type=int, default=200)
    a = ap.parse_args()
    if a.cmd == "seed":
        seed(a.period, a.top)
    else:
        from .collectors import polymarket
        cfg = load_config()
        t = summarize(polymarket.fetch_closed_positions(a.cmd, cfg["track"]["max_positions"]), cfg["track"])
        print(describe(t), "| strength", t["strength"], "| PROVEN" if t["proven"] else "")


if __name__ == "__main__":
    main()
