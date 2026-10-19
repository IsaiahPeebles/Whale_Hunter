"""How much is speed worth? Re-price every settled paper trade as if we had bought earlier.

For a fair comparison every entry time uses the same method: last traded price at that moment
(our side) + the half-spread and slippage we actually saw at detection + the taker fee.
    .venv/bin/python -m whale_hunter.speed
"""
from __future__ import annotations

from statistics import median

from . import db
from .outcomes import paper_return, price_at

DELAYS = [0, 30, 60, 120]  # seconds after the whale's last trade


def rows(conn, cfg):
    out = []
    for r in conn.execute(
            "SELECT p.*, a.ts AS whale_ts, a.detected_ts, a.score, m.result FROM paper_trades p"
            " JOIN alerts a ON a.id=p.alert_id"
            " JOIN markets m ON m.platform=p.platform AND m.market_id=p.market_id"
            " WHERE m.result IS NOT NULL AND a.detected_ts IS NOT NULL"):
        r = dict(r)
        r["won"] = 1.0 if r["result"] == r["direction"] else 0.0
        rate, cost = cfg["fees"][r["platform"]], r["half_spread"] + cfg["paper"]["slippage"]
        times = {f"+{d}s": r["whale_ts"] + d for d in DELAYS}
        times["at detection"] = r["detected_ts"]
        r["ret"] = {}
        for label, t in times.items():
            if t > r["detected_ts"] and label != "at detection":
                continue  # only compare moments before we actually detected it
            p = price_at(conn, r["platform"], r["market_id"], t)
            if p is None:
                continue
            side = p if r["direction"] == "YES" else 1 - p
            entry = min(side + cost, 0.99)
            r["ret"][label] = paper_return(entry, r["won"], rate, True)
        r["lag"] = r["detected_ts"] - r["whale_ts"]
        out.append(r)
    return out


def main():
    from rich.console import Console
    from rich.table import Table

    from .config import load_config
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    data = rows(conn, cfg)
    con = Console()
    labels = [f"+{d}s" for d in DELAYS] + ["at detection"]
    for platform in ("kalshi", "polymarket", None):
        rs = [r for r in data if platform is None or r["platform"] == platform]
        # Same set of trades in every column, so differences are only about timing.
        rs = [r for r in rs if all(l in r["ret"] for l in ("+0s", "at detection"))]
        if not rs:
            continue
        t = Table(title=f"{platform or 'All'}: {len(rs):,} settled bets · median detection lag "
                        f"{median(r['lag'] for r in rs):.0f}s after the whale's last trade")
        t.add_column("Buy at")
        t.add_column("Bets", justify="right")
        t.add_column("Avg return after costs", justify="right")
        for l in labels:
            vals = [r["ret"][l] for r in rs if l in r["ret"]]
            t.add_row(l, f"{len(vals):,}", f"{sum(vals) / len(vals) * 100:+.1f}%")
        con.print(t)


if __name__ == "__main__":
    main()
