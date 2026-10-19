"""Frozen, forward-only strategy test. Only paper trades placed after `strategies.start` count.

    .venv/bin/python -m whale_hunter.strategies
"""
from __future__ import annotations

import json
import math
from datetime import datetime

from . import db
from .outcomes import paper_return


def start_ts(cfg, rule=None):
    """Rules added later carry their own `start`, so their results never include earlier bets."""
    start = (rule or {}).get("start", cfg["strategies"]["start"])
    return datetime.strptime(start, "%Y-%m-%d %H:%M").timestamp()


def matches(rule, t):
    return (t["score"] >= rule.get("min_score", 0)
            and rule.get("platform", t["platform"]) == t["platform"]
            and rule.get("wallet_class", t["cls"]) == t["cls"]
            and rule.get("min_price", 0) <= t["mid"] < rule.get("max_price", 1.01)  # fair price of our side
            and t["opened_ts"] >= t["rule_start"])


def evaluate(conn, cfg):
    """One summary per rule: settled-bet results after spread, slippage and fees."""
    trades = []
    for r in conn.execute(
            "SELECT p.*, a.title, a.score, a.evidence_json, m.result, m.yes_label, m.no_label,"
            " f.filled, f.limit_price FROM paper_trades p"
            " JOIN alerts a ON a.id=p.alert_id"
            " LEFT JOIN markets m ON m.platform=p.platform AND m.market_id=p.market_id"
            " LEFT JOIN maker_fills f ON f.alert_id=p.alert_id"
            " WHERE p.opened_ts >= ?", (min(start_ts(cfg, r) for r in cfg["strategies"]["rules"]),)):
        t = dict(r)
        t["cls"] = (json.loads(t.pop("evidence_json")).get("classes") or ["market"])[0]
        if t["result"]:
            t["won"] = 1.0 if t["result"] == t["direction"] else 0.0
            t["ret"] = paper_return(t["entry_price"], t["won"], cfg["fees"].get(t["platform"], 0), True)
            if t["filled"]:
                t["maker_ret"] = paper_return(t["limit_price"], t["won"], cfg["maker_fees"][t["platform"]], True)
        trades.append(t)
    out = []
    for rule in cfg["strategies"]["rules"]:
        t0 = start_ts(cfg, rule)
        mine = [t for t in trades if matches(rule, dict(t, rule_start=t0))]
        maker = rule.get("entry") == "maker"
        s = {"name": rule["name"], "start": rule.get("start", cfg["strategies"]["start"])}
        if maker:  # only limit orders that actually filled become bets
            decided = [t for t in mine if t["filled"] is not None]
            s["fill_rate"] = sum(t["filled"] for t in decided) / len(decided) if decided else None
            mine = [dict(t, ret=t.get("maker_ret")) for t in decided if t["filled"]]
        settled = [t for t in mine if t["result"]]
        s.update(bets=len(mine), settled=len(settled), open=len(mine) - len(settled), trades=mine)
        if settled:
            n = len(settled)
            edges = [t["won"] - t["mid"] for t in settled]  # did it win more often than the fair price said?
            edge = sum(edges) / n
            sd = math.sqrt(sum((e - edge) ** 2 for e in edges) / max(n - 1, 1))
            s.update(
                win=sum(t["won"] for t in settled) / n,
                fair=sum(t["mid"] for t in settled) / n,
                edge=edge, edge_2se=2 * sd / math.sqrt(n),
                pnl=sum(t["ret"] * t["stake"] for t in settled),
                ret=sum(t["ret"] for t in settled) / n,
                markets=len({(t["platform"], t["market_id"]) for t in settled}),
            )
        out.append(s)
    return out


def main():
    from rich.console import Console
    from rich.table import Table

    from .config import load_config
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    t = Table(title=f"Strategy test — bets placed since {cfg['strategies']['start']} (after spread, slippage, fees)")
    for c in ["Strategy", "Bets", "Settled", "Win %", "Fair %", "Edge (pts)", "Net $", "Return"]:
        t.add_column(c, justify="left" if c == "Strategy" else "right")
    for s in evaluate(conn, cfg):
        if not s["settled"]:
            t.add_row(s["name"], str(s["bets"]), "0", "—", "—", "—", "—", "—")
            continue
        t.add_row(s["name"], str(s["bets"]), str(s["settled"]), f"{s['win'] * 100:.1f}", f"{s['fair'] * 100:.1f}",
                  f"{s['edge'] * 100:+.1f} ± {s['edge_2se'] * 100:.1f}", f"{s['pnl']:+,.0f}", f"{s['ret'] * 100:+.1f}%")
    Console().print(t)


if __name__ == "__main__":
    main()
