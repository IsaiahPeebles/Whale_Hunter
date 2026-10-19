"""Would posting a limit order at the bid (maker) beat paying the ask (taker)?

Fill rule (conservative): our buy at the side's bid fills only if, within the fill window, a taker
trades our side *through* our price, i.e. sells it to someone strictly below our limit.
    .venv/bin/python -m whale_hunter.maker      # backtest every paper trade so far: taker vs maker
"""
from __future__ import annotations

import time

from . import db
from .outcomes import paper_return

EPS = 0.005  # "strictly below" by at least half a cent


def first_fill(conn, platform, market_id, direction, limit, start, end):
    """Timestamp of the first trade that sells our side below our limit, or None."""
    if direction == "YES":  # resting YES bid is hit by takers selling YES (their exposure: NO)
        row = conn.execute(
            "SELECT ts FROM trades WHERE platform=? AND market_id=? AND ts>=? AND ts<=? AND direction='NO'"
            " AND price <= ? ORDER BY ts LIMIT 1", (platform, market_id, start, end, limit - EPS)).fetchone()
    else:  # resting NO bid: YES price must trade at or above 1 - limit + eps
        row = conn.execute(
            "SELECT ts FROM trades WHERE platform=? AND market_id=? AND ts>=? AND ts<=? AND direction='YES'"
            " AND price >= ? ORDER BY ts LIMIT 1", (platform, market_id, start, end, 1 - limit + EPS)).fetchone()
    return row["ts"] if row else None


def simulate(conn, cfg, batch=2000, now=None):
    """Decide fills for paper trades whose window has passed and whose trades we've collected."""
    now = now or time.time()
    window = cfg["maker"]["fill_window_minutes"] * 60
    covered = {p: float(db.get_state(conn, f"last_ts:{p}", 0)) for p in ("kalshi", "polymarket")}
    rows = conn.execute(
        "SELECT p.* FROM paper_trades p LEFT JOIN maker_fills f ON f.alert_id=p.alert_id"
        " WHERE f.alert_id IS NULL AND p.opened_ts + ? <= ? ORDER BY p.opened_ts LIMIT ?",
        (window, now, batch)).fetchall()
    n = 0
    for p in rows:
        end = p["opened_ts"] + window
        if end > covered.get(p["platform"], 0):
            continue  # feed hasn't caught up to the end of the window yet
        limit = p["mid"] - p["half_spread"]
        fill = first_fill(conn, p["platform"], p["market_id"], p["direction"], limit, p["opened_ts"], end)
        conn.execute("INSERT OR IGNORE INTO maker_fills VALUES (?,?,?,?)",
                     (p["alert_id"], limit, int(fill is not None), fill))
        n += 1
    conn.commit()
    return n


def settled_rows(conn, cfg, since=0):
    """Every settled paper trade with both its taker and (if filled) maker return."""
    out = []
    for r in conn.execute(
            "SELECT p.*, f.filled, f.limit_price, m.result FROM paper_trades p"
            " JOIN maker_fills f ON f.alert_id=p.alert_id"
            " JOIN markets m ON m.platform=p.platform AND m.market_id=p.market_id"
            " WHERE m.result IS NOT NULL AND p.opened_ts >= ?", (since,)):
        r = dict(r)
        r["won"] = 1.0 if r["result"] == r["direction"] else 0.0
        r["taker_ret"] = paper_return(r["entry_price"], r["won"], cfg["fees"][r["platform"]], True)
        if r["filled"]:
            r["maker_ret"] = paper_return(r["limit_price"], r["won"], cfg["maker_fees"][r["platform"]], True)
        out.append(r)
    return out


def compare(rows):
    n = len(rows)
    filled = [r for r in rows if r["filled"]]
    missed = [r for r in rows if not r["filled"]]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    return {
        "n": n,
        "taker_ret": avg([r["taker_ret"] for r in rows]),
        "taker_win": avg([r["won"] for r in rows]),
        "fill_rate": len(filled) / n if n else None,
        "maker_ret": avg([r["maker_ret"] for r in filled]),
        "maker_win": avg([r["won"] for r in filled]),
        "missed_win": avg([r["won"] for r in missed]),
        "n_filled": len(filled),
    }


def main():
    from rich.console import Console
    from rich.table import Table

    from .config import load_config
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    con = Console()
    while simulate(conn, cfg, batch=5000):
        pass
    rows = settled_rows(conn, cfg)
    groups = {"All": rows,
              "Kalshi": [r for r in rows if r["platform"] == "kalshi"],
              "Polymarket": [r for r in rows if r["platform"] == "polymarket"]}
    t = Table(title="Taker vs maker on settled paper trades (after spread, slippage and fees)")
    for c in ["Group", "Settled", "Taker return", "Maker fill rate", "Maker return (filled)",
              "Win % taker", "Win % filled", "Win % missed"]:
        t.add_column(c, justify="left" if c == "Group" else "right")
    pct = lambda x: "—" if x is None else f"{x * 100:+.1f}%"
    plain = lambda x: "—" if x is None else f"{x * 100:.1f}%"
    for name, rs in groups.items():
        c = compare(rs)
        if not c["n"]:
            continue
        t.add_row(name, f"{c['n']:,}", pct(c["taker_ret"]), plain(c["fill_rate"]),
                  f"{pct(c['maker_ret'])} (n={c['n_filled']:,})", plain(c["taker_win"]),
                  plain(c["maker_win"]), plain(c["missed_win"]))
    con.print(t)
    con.print("[dim]Win % missed = how often the bets we did NOT get filled on went on to win. "
              "If it's much higher than Win % filled, limit orders mostly catch the losers.[/dim]")


if __name__ == "__main__":
    main()
