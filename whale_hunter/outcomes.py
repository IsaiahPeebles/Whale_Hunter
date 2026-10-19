"""What happened after each alert, and would following it have made money? (CONTEXT §36-37)

Price paths are measured from detection time (when we could actually act), not the whale's trade.
"""
from __future__ import annotations

import json
import time

from . import db

HORIZONS = [0, 300, 1800, 3600, 21600, 86400]  # seconds after detection; -1 = resolution
LABELS = {0: "now", 300: "5m", 1800: "30m", 3600: "1h", 21600: "6h", 86400: "24h", -1: "resolution"}


def price_at(conn, platform, market_id, ts):
    row = conn.execute(
        "SELECT price FROM trades WHERE platform=? AND market_id=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (platform, market_id, ts)).fetchone()
    return row["price"] if row else None


def record_outcomes(conn, now=None):
    """Fill in matured horizons. Only uses data we have actually collected up to that time."""
    now = now or time.time()
    covered = {p: float(db.get_state(conn, f"last_ts:{p}", 0)) for p in ("kalshi", "polymarket")}
    n = 0
    for h in HORIZONS:
        rows = conn.execute(
            "SELECT a.id, a.platform, a.market_id, a.detected_ts, m.result, m.close_time FROM alerts a"
            " LEFT JOIN markets m ON m.platform=a.platform AND m.market_id=a.market_id"
            " WHERE a.detected_ts IS NOT NULL AND a.detected_ts + ? <= ?"
            " AND NOT EXISTS (SELECT 1 FROM signal_outcomes o WHERE o.alert_id=a.id AND o.horizon_s=?)"
            " LIMIT 5000", (h, now, h)).fetchall()
        for r in rows:
            due = r["detected_ts"] + h
            if r["result"] and r["close_time"] and r["close_time"] <= due:
                price = 1.0 if r["result"] == "YES" else 0.0
            elif due <= covered.get(r["platform"], 0):
                price = price_at(conn, r["platform"], r["market_id"], due)
            else:
                continue  # feed hasn't caught up to this time yet
            if price is not None:
                conn.execute("INSERT OR IGNORE INTO signal_outcomes VALUES (?,?,?,?)", (r["id"], h, price, now))
                n += 1
    # Final resolution for every alert on a resolved market.
    n += conn.execute(
        "INSERT OR IGNORE INTO signal_outcomes SELECT a.id, -1, CASE m.result WHEN 'YES' THEN 1.0 ELSE 0.0 END, ?"
        " FROM alerts a JOIN markets m ON m.platform=a.platform AND m.market_id=a.market_id"
        " WHERE m.result IS NOT NULL", (now,)).rowcount
    conn.commit()
    return n


def markets_to_resolve(conn, cfg, now=None):
    """Alerted markets with no result yet, whose metadata is older than the check interval."""
    now = now or time.time()
    cutoff = now - cfg["paper"]["resolution_check_minutes"] * 60
    rows = conn.execute(
        "SELECT DISTINCT m.platform, m.market_id FROM markets m JOIN alerts a"
        " ON a.platform=m.platform AND a.market_id=m.market_id"
        " WHERE m.result IS NULL AND COALESCE(m.meta_updated_ts, 0) < ?"
        " AND (m.close_time IS NULL OR m.close_time < ? + 86400) LIMIT 300", (cutoff, now)).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["platform"], []).append(r["market_id"])
    return out


def open_paper_trades(conn, alert_ids, cfg, fetch_markets_by_platform, now=None):
    """Enter at the live ask for each qualifying new alert. fetch: {platform: fn(ids) -> markets}."""
    pc, now = cfg["paper"], now or time.time()
    alerts = [dict(r) for r in conn.execute(
        f"SELECT * FROM alerts WHERE id IN ({','.join('?' * len(alert_ids))}) AND score >= ?",
        (*alert_ids, pc["min_score"]))] if alert_ids else []
    fresh, seen = [], set()
    for a in sorted(alerts, key=lambda a: -a["score"]):
        key = (a["platform"], a["market_id"], a["direction"], a["kind"])
        if key in seen:
            continue
        seen.add(key)
        dup = conn.execute(
            "SELECT 1 FROM paper_trades p JOIN alerts x ON x.id=p.alert_id WHERE p.platform=? AND"
            " p.market_id=? AND p.direction=? AND x.kind=? AND p.opened_ts > ?",
            (a["platform"], a["market_id"], a["direction"], a["kind"], now - pc["dedupe_hours"] * 3600),
        ).fetchone()
        if not dup:
            fresh.append(a)
    quotes = {}
    for platform in {a["platform"] for a in fresh}:
        ids = list({a["market_id"] for a in fresh if a["platform"] == platform})
        try:
            for m in fetch_markets_by_platform[platform](ids):
                quotes[(platform, m["market_id"])] = m
                db.upsert_market(conn, m)
        except Exception:
            continue
    opened = 0
    for a in fresh:
        q = quotes.get((a["platform"], a["market_id"]))
        if not q or q.get("bid") is None or q.get("ask") is None or q["ask"] <= q["bid"]:
            continue
        bid, ask = (q["bid"], q["ask"]) if a["direction"] == "YES" else (1 - q["ask"], 1 - q["bid"])
        entry = ask + pc["slippage"]
        if entry > pc["max_entry_price"]:
            continue
        conn.execute("INSERT OR IGNORE INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?)",
                     (a["id"], now, a["platform"], a["market_id"], a["direction"], (bid + ask) / 2,
                      entry, (ask - bid) / 2, pc["stake"]))
        opened += 1
    conn.commit()
    return opened


def paper_return(entry, exit_price, rate, settled):
    """Return per $ staked after taker fees (fee = shares × rate × p × (1 − p)).

    Buying always pays the fee; selling early pays it again on the exit price; settlement is free.
    """
    ret = exit_price / entry - 1 - rate * (1 - entry)
    if not settled:
        ret -= exit_price / entry * rate * (1 - exit_price)
    return ret


def _side(price_yes, direction):
    return price_yes if direction == "YES" else 1 - price_yes


def performance(conn, fees=None):
    """Per-alert rows with signal moves (pts) and paper returns (fraction of stake) per exit rule."""
    outs = {}
    for r in conn.execute("SELECT * FROM signal_outcomes"):
        outs.setdefault(r["alert_id"], {})[r["horizon_s"]] = r["price"]
    rows = []
    for a in conn.execute("SELECT a.*, p.entry_price, p.half_spread, p.mid FROM alerts a"
                          " LEFT JOIN paper_trades p ON p.alert_id=a.id WHERE a.detected_ts IS NOT NULL"):
        o = outs.get(a["id"], {})
        if 0 not in o:
            continue
        ev = json.loads(a["evidence_json"])
        row = {"id": a["id"], "kind": a["kind"], "severity": a["severity"], "confidence": a["confidence"],
               "score": a["score"], "platform": a["platform"],
               "cls": (ev.get("classes") or ["market"])[0], "move": {}, "ret": {}}
        start = _side(o[0], a["direction"])
        for h, p in o.items():
            if h > 0 or h == -1:
                row["move"][h] = (_side(p, a["direction"]) - start) * 100
        if a["entry_price"]:
            row["paper"] = True
            rate = (fees or {}).get(a["platform"], 0)
            for h, p in o.items():
                if h == -1:
                    row["ret"][h] = paper_return(a["entry_price"], _side(p, a["direction"]), rate, True)
                elif h > 0:
                    row["ret"][h] = paper_return(a["entry_price"], max(_side(p, a["direction"]) - a["half_spread"], 0),
                                                 rate, False)
        rows.append(row)
    return rows


def summarize(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    out = []
    for g, rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        s = {"group": g, "alerts": len(rs), "paper": sum(1 for r in rs if r.get("paper")), "cols": {}}
        for h in HORIZONS[1:] + [-1]:
            moves = [r["move"][h] for r in rs if h in r["move"]]
            rets = [r["ret"][h] for r in rs if h in r["ret"]]
            s["cols"][h] = {
                "n": len(moves),
                "avg_move": sum(moves) / len(moves) if moves else None,
                "hit": sum(m > 0 for m in moves) / len(moves) if moves else None,
                "n_paper": len(rets),
                "avg_ret": sum(rets) / len(rets) if rets else None,
            }
        out.append(s)
    return out


def score_bucket(r):
    return "90+" if r["score"] >= 90 else "75-89" if r["score"] >= 75 else "60-74" if r["score"] >= 60 else "<60"


GROUPINGS = {
    "Alert type": lambda r: r["kind"] if r["kind"] == "market" else f"wallet: {r['cls']}",
    "Score": score_bucket,
    "Confidence": lambda r: r["confidence"],
    "Platform": lambda r: r["platform"],
}


def report(conn, fees=None):
    rows = performance(conn, fees)
    return {name: summarize(rows, fn) for name, fn in GROUPINGS.items()}, rows


def main():
    from rich.console import Console
    from rich.table import Table

    from .config import load_config
    cfg = load_config()
    conn = db.connect(cfg["db_path"])
    record_outcomes(conn)
    tables, rows = report(conn, cfg["fees"])
    con = Console()
    con.print(f"[bold]{len(rows)} alerts with outcomes, {sum(1 for r in rows if r.get('paper'))} paper trades[/bold]"
              f"  (move = probability pts in alert direction from detection; return = paper P&L incl. costs)")
    for name, groups in tables.items():
        t = Table(title=name)
        t.add_column("group")
        t.add_column("alerts", justify="right")
        for h in [300, 3600, 21600, 86400, -1]:
            t.add_column(f"{LABELS[h]} move / hit / ret", justify="right")
        for g in groups:
            cells = []
            for h in [300, 3600, 21600, 86400, -1]:
                c = g["cols"][h]
                if not c["n"]:
                    cells.append("—")
                    continue
                ret = f"{c['avg_ret'] * 100:+.1f}% (n={c['n_paper']})" if c["avg_ret"] is not None else "no paper"
                flag = "" if c["n"] >= cfg["paper"]["min_sample"] else " [dim]small n[/dim]"
                cells.append(f"{c['avg_move']:+.1f}pt / {c['hit'] * 100:.0f}% / {ret}{flag}")
            t.add_row(str(g["group"]), str(g["alerts"]), *cells)
        con.print(t)


if __name__ == "__main__":
    main()
