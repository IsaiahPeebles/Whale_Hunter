"""SQLite storage. Raw JSON is kept on markets and trades so detection can be rebuilt later."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    platform TEXT NOT NULL,
    market_id TEXT NOT NULL,
    event_id TEXT,
    title TEXT,
    yes_label TEXT,
    no_label TEXT,
    url TEXT,
    status TEXT,
    open_time REAL,
    close_time REAL,
    last_trade_ts REAL,
    meta_updated_ts REAL,
    backfilled INTEGER DEFAULT 0,
    raw_json TEXT,
    PRIMARY KEY (platform, market_id)
);
CREATE TABLE IF NOT EXISTS market_snapshots (
    platform TEXT NOT NULL,
    market_id TEXT NOT NULL,
    ts REAL NOT NULL,
    price REAL,
    bid REAL,
    ask REAL,
    liquidity REAL,
    liquidity_kind TEXT,
    volume_24h REAL,
    open_interest REAL
);
CREATE INDEX IF NOT EXISTS ix_snap ON market_snapshots (platform, market_id, ts);
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    market_id TEXT NOT NULL,
    ts REAL NOT NULL,
    price REAL NOT NULL,      -- YES (outcome 0) probability, 0..1
    size REAL NOT NULL,       -- contracts / shares
    notional REAL NOT NULL,   -- USD paid by the taker
    direction TEXT NOT NULL,  -- YES | NO (taker's directional exposure)
    taker INTEGER NOT NULL,
    wallet TEXT,
    raw_json TEXT             -- no longer written (normalized columns hold everything used); kept for old rows
);
CREATE INDEX IF NOT EXISTS ix_trades_market_ts ON trades (platform, market_id, ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    platform TEXT NOT NULL,
    market_id TEXT NOT NULL,
    title TEXT,
    direction TEXT,
    score REAL,
    severity TEXT,
    confidence TEXT,
    headline TEXT,
    evidence_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_ts ON alerts (ts);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
-- Simulated maker (limit-order) entry for each paper trade, decided once its fill window has passed.
CREATE TABLE IF NOT EXISTS maker_fills (
    alert_id INTEGER PRIMARY KEY,
    limit_price REAL NOT NULL,   -- side bid when the alert fired
    filled INTEGER NOT NULL,
    fill_ts REAL
);
CREATE TABLE IF NOT EXISTS poll_log (  -- per-poll counts, so the dashboard never scans trades
    ts REAL NOT NULL,
    platform TEXT NOT NULL,
    new_trades INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_poll_log_ts ON poll_log (ts);
CREATE TABLE IF NOT EXISTS wallets (
    wallet TEXT PRIMARY KEY,
    first_seen_ts REAL,        -- first observed Polymarket activity (NOT wallet creation)
    last_prior_trade_ts REAL,  -- last trade before the position that triggered the lookup
    markets_traded INTEGER,
    observable_value REAL,     -- current open-position value; not total wealth
    fetched_ts REAL NOT NULL     -- profile fetch time; 0 = profile never fetched
);
-- Price path after each alert, measured from detection time (when we could have acted).
CREATE TABLE IF NOT EXISTS signal_outcomes (
    alert_id INTEGER NOT NULL,
    horizon_s INTEGER NOT NULL,  -- 0 = at detection, -1 = final resolution
    price REAL NOT NULL,         -- YES price at detected_ts + horizon (1/0 at resolution)
    recorded_ts REAL NOT NULL,
    PRIMARY KEY (alert_id, horizon_s)
);
CREATE TABLE IF NOT EXISTS paper_trades (
    alert_id INTEGER PRIMARY KEY,
    opened_ts REAL NOT NULL,
    platform TEXT NOT NULL,
    market_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    mid REAL NOT NULL,           -- side mid price at entry
    entry_price REAL NOT NULL,   -- price paid per share of the chosen side, incl. spread + slippage
    half_spread REAL NOT NULL,   -- charged again on time-based exits
    stake REAL NOT NULL
);
"""

# Columns added after v1; applied to existing databases on connect.
MIGRATIONS = [
    ("alerts", "kind", "TEXT DEFAULT 'market'"),
    ("alerts", "wallet", "TEXT"),
    ("alerts", "detected_ts", "REAL"),   # wall-clock time we raised it (feeds lag trade time)
    ("markets", "result", "TEXT"),       # YES | NO once resolved
    ("wallets", "username", "TEXT"),
    ("wallets", "track_n", "INTEGER"),   # recent closed positions evaluated
    ("wallets", "track_wins", "INTEGER"),
    ("wallets", "track_pnl", "REAL"),
    ("wallets", "track_invested", "REAL"),
    ("wallets", "track_strength", "REAL"),  # 0..1 after sample-size shrinkage; NULL = too few
    ("wallets", "proven", "INTEGER DEFAULT 0"),
    ("wallets", "track_fetched_ts", "REAL"),
]


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, col, decl in MIGRATIONS:
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    return conn


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()


def insert_trades(conn, trades: list[dict]) -> list[dict]:
    """Insert normalized trades; returns only the ones that were new."""
    new = []
    for t in trades:
        cur = conn.execute(
            "INSERT OR IGNORE INTO trades (trade_id, platform, market_id, ts, price, size, notional,"
            " direction, taker, wallet) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (t["trade_id"], t["platform"], t["market_id"], t["ts"], t["price"], t["size"],
             t["notional"], t["direction"], int(t["taker"]), t.get("wallet")),
        )
        if cur.rowcount:
            new.append(t)
    # Register any market we have not seen; metadata is filled in later.
    for (platform, market_id), ts in _latest_ts(new).items():
        conn.execute(
            "INSERT INTO markets (platform, market_id, last_trade_ts) VALUES (?,?,?)"
            " ON CONFLICT(platform, market_id) DO UPDATE SET"
            " last_trade_ts = MAX(COALESCE(last_trade_ts, 0), excluded.last_trade_ts)",
            (platform, market_id, ts),
        )
    conn.commit()
    return new


def _latest_ts(trades):
    out = {}
    for t in trades:
        k = (t["platform"], t["market_id"])
        out[k] = max(out.get(k, 0), t["ts"])
    return out


def upsert_market(conn, m: dict):
    conn.execute(
        "INSERT INTO markets (platform, market_id, event_id, title, yes_label, no_label, url, status,"
        " open_time, close_time, meta_updated_ts, raw_json, result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(platform, market_id) DO UPDATE SET"
        " event_id=COALESCE(excluded.event_id, event_id), title=COALESCE(excluded.title, title),"
        " yes_label=COALESCE(excluded.yes_label, yes_label), no_label=COALESCE(excluded.no_label, no_label),"
        " url=COALESCE(excluded.url, url), status=COALESCE(excluded.status, status),"
        " open_time=COALESCE(excluded.open_time, open_time),"
        " close_time=COALESCE(excluded.close_time, close_time), meta_updated_ts=excluded.meta_updated_ts,"
        " raw_json=excluded.raw_json, result=COALESCE(excluded.result, result)",
        (m["platform"], m["market_id"], m.get("event_id"), m.get("title"), m.get("yes_label"),
         m.get("no_label"), m.get("url"), m.get("status"), m.get("open_time"), m.get("close_time"),
         m["ts"], json.dumps(m.get("raw")), m.get("result")),
    )
    conn.execute(
        "INSERT INTO market_snapshots (platform, market_id, ts, price, bid, ask, liquidity,"
        " liquidity_kind, volume_24h, open_interest) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (m["platform"], m["market_id"], m["ts"], m.get("price"), m.get("bid"), m.get("ask"),
         m.get("liquidity"), m.get("liquidity_kind"), m.get("volume_24h"), m.get("open_interest")),
    )


def get_market(conn, platform, market_id):
    return conn.execute(
        "SELECT * FROM markets WHERE platform=? AND market_id=?", (platform, market_id)
    ).fetchone()


def latest_snapshot(conn, platform, market_id):
    return conn.execute(
        "SELECT * FROM market_snapshots WHERE platform=? AND market_id=? ORDER BY ts DESC LIMIT 1",
        (platform, market_id),
    ).fetchone()


def trades_between(conn, platform, market_id, start, end):
    return [dict(r) for r in conn.execute(
        "SELECT ts, price, size, notional, direction, taker, wallet FROM trades"
        " WHERE platform=? AND market_id=? AND ts>=? AND ts<=? ORDER BY ts",
        (platform, market_id, start, end),
    )]


def insert_alert(conn, a: dict):
    cur = conn.execute(
        "INSERT INTO alerts (ts, platform, market_id, title, direction, score, severity, confidence,"
        " headline, evidence_json, kind, wallet, detected_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (a["ts"], a["platform"], a["market_id"], a["title"], a["direction"], a["score"],
         a["severity"], a["confidence"], a["headline"], json.dumps(a["evidence"]),
         a.get("kind", "market"), a.get("wallet"), a.get("detected_ts", time.time())),
    )
    conn.commit()
    return cur.lastrowid


def last_alert(conn, platform, market_id, direction, kind="market", wallet=None):
    return conn.execute(
        "SELECT * FROM alerts WHERE platform=? AND market_id=? AND direction=? AND kind=?"
        " AND COALESCE(wallet, '')=? ORDER BY ts DESC LIMIT 1",
        (platform, market_id, direction, kind, wallet or ""),
    ).fetchone()


def get_wallet(conn, wallet):
    return conn.execute("SELECT * FROM wallets WHERE wallet=?", (wallet,)).fetchone()


def upsert_wallet(conn, w: dict, ts):
    conn.execute(
        "INSERT INTO wallets (wallet, first_seen_ts, last_prior_trade_ts, markets_traded,"
        " observable_value, fetched_ts) VALUES (?,?,?,?,?,?) ON CONFLICT(wallet) DO UPDATE SET"
        " first_seen_ts=excluded.first_seen_ts, last_prior_trade_ts=excluded.last_prior_trade_ts,"
        " markets_traded=excluded.markets_traded, observable_value=excluded.observable_value,"
        " fetched_ts=excluded.fetched_ts",
        (w["wallet"], w["first_seen_ts"], w["last_prior_trade_ts"], w["markets_traded"],
         w["observable_value"], ts),
    )
    conn.commit()


def upsert_track(conn, wallet, t: dict, ts, username=None):
    conn.execute(
        "INSERT INTO wallets (wallet, username, track_n, track_wins, track_pnl, track_invested,"
        " track_strength, proven, track_fetched_ts, fetched_ts) VALUES (?,?,?,?,?,?,?,?,?,0)"
        " ON CONFLICT(wallet) DO UPDATE SET username=COALESCE(excluded.username, username),"
        " track_n=excluded.track_n, track_wins=excluded.track_wins, track_pnl=excluded.track_pnl,"
        " track_invested=excluded.track_invested, track_strength=excluded.track_strength,"
        " proven=excluded.proven, track_fetched_ts=excluded.track_fetched_ts",
        (wallet, username, t["n"], t["wins"], t["pnl"], t["invested"], t["strength"],
         int(t["proven"]), ts),
    )
    conn.commit()


def proven_wallets(conn):
    return {r["wallet"] for r in conn.execute("SELECT wallet FROM wallets WHERE proven=1")}
