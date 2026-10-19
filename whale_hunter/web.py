"""Minimal dashboard: markets ranked by latest Whale Score + recent alert feed (CONTEXT §32)."""
from __future__ import annotations

import json
import time
from datetime import datetime

from flask import Flask, render_template, request

from . import db
from .config import load_config
from .outcomes import LABELS, paper_return, report
from .strategies import evaluate as evaluate_strategies

app = Flask(__name__)
cfg = load_config()


@app.template_filter("clock")
def clock(ts):
    return datetime.fromtimestamp(ts).strftime("%b %d %H:%M")


@app.route("/")
def index():
    hours = float(request.args.get("hours", 24))
    conn = db.connect(cfg["db_path"])
    since = time.time() - hours * 3600
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM alerts WHERE ts > ? ORDER BY ts DESC LIMIT 500", (since,))]
    for r in rows:
        r["ev"] = json.loads(r["evidence_json"])
    # Ranking: each market's strongest alert in the period.
    best = {}
    wallet_rows = [r for r in rows if r["kind"] == "wallet"][:40]
    for r in rows:
        if r["kind"] == "wallet":
            continue
        k = (r["platform"], r["market_id"])
        if k not in best or r["score"] > best[k]["score"]:
            best[k] = r
    ranked = sorted(best.values(), key=lambda r: -r["score"])[:50]
    # Never scan the trades table here (tens of millions of rows); use the poll log and state.
    stats = [{"platform": p, "last": float(db.get_state(conn, f"last_ts:{p}", 0))}
             for p in ("kalshi", "polymarket")]
    tables, perf_rows = report(conn, cfg["fees"])
    now = time.time()
    last_cycle = float(db.get_state(conn, "last_cycle_ts", 0))
    paper = [r for r in perf_rows if r.get("paper")]
    kpi = {
        "alive": now - last_cycle < 120,
        "last_cycle_ago": now - last_cycle if last_cycle else None,
        "trades_1h": conn.execute("SELECT COALESCE(SUM(new_trades), 0) FROM poll_log WHERE ts > ?",
                                  (now - 3600,)).fetchone()[0],
        "alerts": len(rows),
        "wallet_alerts": len(wallet_rows),
        "proven": conn.execute("SELECT COUNT(*) FROM wallets WHERE proven=1").fetchone()[0],
        "paper_total": conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0],
        "paper_resolved": sum(1 for r in paper if -1 in r["ret"]),
        "paper_ret_res": _avg([r["ret"][-1] for r in paper if -1 in r["ret"]]),
        "paper_ret_6h": _avg([r["ret"][21600] for r in paper if 21600 in r["ret"]]),
        "paper_n_6h": sum(1 for r in paper if 21600 in r["ret"]),
    }
    bets = paper_bets(conn)
    kpi["bets_pnl"] = sum(b["pnl"] for b in bets if b["pnl"] is not None)
    strategies = evaluate_strategies(conn, cfg)
    conn.close()
    return render_template("index.html", ranked=ranked, wallets=wallet_rows, feed=rows[:80],
                           stats=stats, hours=hours, kpi=kpi, scoreboard=tables["Alert type"], bets=bets,
                           strategies=strategies, strategy_start=cfg["strategies"]["start"],
                           horizons=[3600, 21600, 86400, -1], labels=LABELS,
                           min_sample=cfg["paper"]["min_sample"])


BET_FILTERS = {
    "all": "1=1",
    "open": "m.result IS NULL",
    "settled": "m.result IS NOT NULL",
    "won": "m.result = p.direction",
    "lost": "m.result IS NOT NULL AND m.result != p.direction",
}
BET_JOIN = (" FROM paper_trades p JOIN alerts a ON a.id=p.alert_id"
            " LEFT JOIN markets m ON m.platform=p.platform AND m.market_id=p.market_id")
SOURCE_SQL = ("CASE WHEN a.kind='market' THEN 'market' ELSE lower(replace(COALESCE("
              "json_extract(a.evidence_json, '$.classes[0]'), 'wallet'), ' WALLET', '')) || ' wallet' END")


def paper_bets(conn, limit=60, status="all", offset=0):
    """Paper trades newest first, marked to the latest traded price (or settled if resolved)."""
    bets = []
    for r in conn.execute(
            "SELECT p.*, a.title, a.kind, a.score, a.evidence_json, m.result, m.yes_label, m.no_label"
            + BET_JOIN + f" WHERE {BET_FILTERS[status]} ORDER BY p.opened_ts DESC LIMIT ? OFFSET ?",
            (limit, offset)):
        b = dict(r)
        ev = json.loads(b.pop("evidence_json"))
        b["label"] = (b["yes_label"] if b["direction"] == "YES" else b["no_label"]) or b["direction"]
        b["source"] = "market" if b["kind"] == "market" else (ev.get("classes") or ["wallet"])[0].replace(" WALLET", "").lower() + " wallet"
        last = conn.execute("SELECT price FROM trades WHERE platform=? AND market_id=? ORDER BY ts DESC LIMIT 1",
                            (b["platform"], b["market_id"])).fetchone()
        rate = cfg["fees"].get(b["platform"], 0)
        if b["result"]:
            b["now"] = 1.0 if b["result"] == b["direction"] else 0.0
            b["status"] = "won" if b["now"] == 1.0 else "lost"
            b["pnl"] = b["stake"] * paper_return(b["entry_price"], b["now"], rate, True)
        elif last:
            b["now"] = last["price"] if b["direction"] == "YES" else 1 - last["price"]
            b["status"] = "open"
            # what selling right now would fetch, after the spread and the exit fee
            b["pnl"] = b["stake"] * paper_return(b["entry_price"], max(b["now"] - b["half_spread"], 0), rate, False)
        else:
            b["now"], b["status"], b["pnl"] = None, "open", None
        bets.append(b)
    return bets


def _avg(xs):
    return sum(xs) / len(xs) if xs else None


@app.route("/bets")
def bets_page():
    status = request.args.get("status", "settled")
    status = status if status in BET_FILTERS else "settled"
    page = max(request.args.get("page", 1, type=int), 1)  # bad values fall back to 1
    per_page = 100
    conn = db.connect(cfg["db_path"])
    counts = {k: conn.execute(f"SELECT COUNT(*){BET_JOIN} WHERE {w}").fetchone()[0]
              for k, w in BET_FILTERS.items()}
    # Settled bets pay $1/share if they won, $0 if they lost.
    summary = [dict(r) for r in conn.execute(
        f"SELECT {SOURCE_SQL} src, COUNT(*) n, SUM(m.result = p.direction) won, SUM(p.stake) staked,"
        " SUM(p.stake * ((CASE WHEN m.result = p.direction THEN 1.0 / p.entry_price ELSE 0 END) - 1"
        "   - (CASE p.platform WHEN 'kalshi' THEN ? ELSE ? END) * (1 - p.entry_price))) pnl,"  # taker fee on entry
        " AVG(p.entry_price) avg_paid"
        + BET_JOIN + " WHERE m.result IS NOT NULL GROUP BY src ORDER BY n DESC",
        (cfg["fees"]["kalshi"], cfg["fees"]["polymarket"]))]
    total = {k: sum(r[k] for r in summary) for k in ("n", "won", "staked", "pnl")}
    rows = paper_bets(conn, per_page, status, (page - 1) * per_page)
    conn.close()
    return render_template("bets.html", bets=rows, status=status, counts=counts, page=page,
                           pages=max((counts[status] + per_page - 1) // per_page, 1),
                           summary=summary, total=total, min_sample=cfg["paper"]["min_sample"])


@app.route("/strategy/<int:i>")
def strategy_page(i):
    """One strategy's bets from the frozen test, with the same matching and costs as the scorecard."""
    conn = db.connect(cfg["db_path"])
    strategies = evaluate_strategies(conn, cfg)
    conn.close()
    if not 0 <= i < len(strategies):
        return "No such strategy", 404
    s = strategies[i]
    maker = cfg["strategies"]["rules"][i].get("entry") == "maker"
    for t in s["trades"]:
        t["paid"] = t["limit_price"] if maker else t["entry_price"]
        t["label"] = (t["yes_label"] if t["direction"] == "YES" else t["no_label"]) or t["direction"]
        t["status"] = "open" if not t["result"] else "won" if t["won"] else "lost"
        t["pnl"] = t["ret"] * t["stake"] if t["result"] else None
    groups = {"settled": [t for t in s["trades"] if t["result"]],
              "won": [t for t in s["trades"] if t["status"] == "won"],
              "lost": [t for t in s["trades"] if t["status"] == "lost"],
              "open": [t for t in s["trades"] if not t["result"]],
              "all": s["trades"]}
    status = request.args.get("status", "settled")
    status = status if status in groups else "settled"
    page = max(request.args.get("page", 1, type=int), 1)  # bad values fall back to 1
    per_page = 100
    rows = sorted(groups[status], key=lambda t: -t["opened_ts"])
    return render_template("strategy.html", i=i, s=s, groups=groups, status=status, page=page,
                           bets=rows[(page - 1) * per_page:page * per_page],
                           pages=max((len(rows) + per_page - 1) // per_page, 1),
                           won_pnl=sum(t["pnl"] for t in groups["won"]),
                           lost_pnl=sum(t["pnl"] for t in groups["lost"]),
                           strategy_start=s["start"])


@app.route("/performance")
def performance():
    conn = db.connect(cfg["db_path"])
    tables, rows = report(conn, cfg["fees"])
    proven = [dict(r) for r in conn.execute(
        "SELECT * FROM wallets WHERE proven=1 ORDER BY track_strength DESC LIMIT 100")]
    conn.close()
    return render_template("performance.html", tables=tables, n_rows=len(rows),
                           n_paper=sum(1 for r in rows if r.get("paper")), proven=proven,
                           horizons=[300, 3600, 21600, 86400, -1], labels=LABELS,
                           min_sample=cfg["paper"]["min_sample"], stake=cfg["paper"]["stake"])


def serve(port=8050):
    app.run(port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    serve()
