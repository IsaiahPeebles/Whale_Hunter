# AGENTS.md

Instructions for AI coding assistants (Claude Code, Codex, Cursor, etc.) working in this repo.
Humans: see [README.md](README.md). The full design spec is [CONTEXT.md](CONTEXT.md).

## If the user asks you to "set up", "spin up", or "run" the project

1. **Verify setup.** Run `python3 start.py --check` (on Windows, `py start.py --check`). It creates `.venv`, installs the pinned requirements and runs the tests. All tests should pass. No API keys, accounts or `.env` are needed, because both data sources are public.
2. **Start the app as a background/long-running process.** Run `python3 start.py --no-browser`. It never exits on its own. Don't run it in the foreground and wait for it to finish.
3. **Confirm it's healthy.** After ~10 seconds, `http://localhost:8050` should return HTTP 200. Within ~30 seconds the log should show lines like `kalshi: N new trades across M markets` every 20 seconds.
4. **Tell the user** to open http://localhost:8050 and set expectations (next section). If they're on a desktop, plain `python3 start.py` opens the browser for them.

If port 8050 is taken, use `--port <other>`. `start.py` refuses to start on a busy port and says so.

### What a fresh install looks like (so you don't misreport it as broken)
- The database starts empty, so the dashboard is sparse at first. Trades appear immediately and the first alerts usually arrive within a minute or two; more build up as baselines fill in.
- Paper bets only settle when their markets resolve (hours to days), so performance and strategy panels stay mostly empty early on.
- The strategy test counts bets placed after the `start` dates in `config.yaml`. Those dates are in the past, so all new bets count.
- **Disk usage:** about 3 GB/day in `data/whale.db`. Old trades are pruned after `trades_retention_days` (21). Warn the user before leaving it running for days.

## Repo map

| Path | What it is |
|---|---|
| `start.py` | Cross-platform bootstrap and launcher (stdlib only) |
| `whale_hunter/__main__.py` | Runs collector loop + Flask dashboard together (`WHALE_PORT` env sets port) |
| `whale_hunter/main.py` | Poll → candidates → metadata → backfill → score → alert loop |
| `whale_hunter/collectors/` | Kalshi and Polymarket trade feeds, normalized to one schema |
| `whale_hunter/score.py`, `detect.py`, `baseline.py` | Whale Score relative to each market's own baseline |
| `whale_hunter/wallets.py`, `track.py` | Polymarket wallet profiling and track records |
| `whale_hunter/outcomes.py`, `strategies.py`, `maker.py`, `speed.py` | Paper trading, frozen strategy test, experiments |
| `whale_hunter/web.py`, `templates/` | Dashboard (`/`, `/bets`, `/performance`, `/strategy/<n>`) |
| `config.yaml` | Every threshold, weight, fee and strategy rule |
| `tests/` | pytest suite (`.venv/bin/python -m pytest -q tests`) |
| `export/strategy_scorecard.txt` | Final results from the original Oct 2026 run (cited in README) |
| `data/` | SQLite database, created on first run (git-ignored) |

Code comments like `CONTEXT §15` refer to sections of `CONTEXT.md`.

## Conventions
- **Keep it lean.** The project deliberately avoids frameworks and over-engineering. Match the existing style: small modules, plain functions, sqlite3 directly.
- **Tunables belong in `config.yaml`,** not hard-coded.
- **Strategy rules are a frozen, forward-only test.** Don't edit or reorder existing rules in `config.yaml` `strategies.rules`. To try a new idea, add a new rule with its own `start:` time.
- **Paper results must stay honest.** Entries are at the live ask + slippage + fees, never the whale's price. Don't "improve" results by removing costs.
- Python 3.9 compatible (CI runs 3.9). Run the tests after changes.
- **Ask the user before** deleting `data/`, changing retention or fees, or running a `VACUUM`.

## Troubleshooting
- `python3: command not found` → install Python 3.9+ from python.org (Windows: use `py`).
- Dependency install fails → delete `.venv/` and rerun `start.py`.
- `poll failed` warnings → usually a temporary API outage or network issue. The loop keeps running.
- Want a clean slate → stop the app and delete `data/` (ask the user first if it holds data they care about).
