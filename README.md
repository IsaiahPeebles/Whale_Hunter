# 🐋 Whale Hunter

![tests](../../actions/workflows/tests.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

**A real-time detector for unusual "whale" trading on prediction markets (Kalshi and Polymarket), plus a paper-trading test of whether following those whales actually makes money.**

It watches every trade on both platforms, flags activity that is abnormal *for that specific market*, explains why each alert fired, and then tracks what happened afterwards. I ran it nonstop for about a week and collected more than 25,000 simulated bets to test the idea honestly.

> **Short answer:** whales are easy to spot, but betting alongside them doesn't make money once real trading costs are counted. The [Results](#results) section explains why.

---

## Why I built it

On prediction markets, a sudden $50k bet can mean someone knows something, or it can mean nothing at all. A $50k trade is routine in a market that trades $5M a day and extraordinary in one that trades $20k a day. I wanted to know two things:

1. Can I detect genuinely unusual activity across *every* market automatically, without hand-picking a watchlist?
2. If so, is there a profitable edge in following it?

## What it does

- **Watches everything.** It polls both platforms' global trade feeds every 20 seconds, and markets register themselves the moment they trade. There's no catalog crawl; Kalshi alone lists 80k+ open markets.
- **Judges trades relative to each market.** Every market gets its own 7-day baseline, so the same dollar amount scores very differently in a busy market and a quiet one.
- **Gives each alert an explained Whale Score (0–100).** Seven signals are combined: trade size, volume spike, clustering, price impact, liquidity impact, aggression and accumulation. Each alert says which signals fired and why.
- **Profiles wallets (Polymarket).** It flags brand-new, low-history and long-dormant wallets that suddenly place large bets. It also scores wallets on their real track record (realized ROI over their last 200 closed positions, shrunk toward zero for small samples), so a "98% win rate" from buying 99¢ favorites doesn't fool it.
- **Paper-trades every strong alert.** It enters at the *live ask when the alert fires* (not the whale's price), adds 1¢ slippage and real fee schedules, and tracks the price at 5m/30m/1h/6h/24h and at resolution.
- **Runs a frozen, forward-only strategy test.** Rules are fixed before the data comes in, and only bets placed after the start time count. This prevents the results from being tuned to data I'd already seen.
- **Includes a local dashboard** (Flask) with live alerts, open and settled bets, performance breakdowns and per-strategy drill-downs.

## Results

These are forward-only results from Oct 9–12, 2026 (Kalshi + Polymarket). Each paper bet was $100, measured after spread, slippage and fees.

| Strategy | Settled bets | Win % | Fair % | Edge (pts) | Return |
|---|---:|---:|---:|---:|---:|
| All alerts (control) | 17,773 | 59.8 | 59.8 | −0.0 ± 0.7 | **−8.6%** |
| Polymarket, score 75+ | 1,015 | 60.0 | 59.1 | +0.9 ± 2.7 | −12.2% |
| Score 90+ | 1,405 | 69.0 | 67.8 | +1.1 ± 2.2 | −7.5% |
| Proven wallets | 1,155 | 53.2 | 51.9 | +1.2 ± 2.6 | −8.1% |
| All alerts, maker (limit) entry | 8,587 | 52.4 | 59.4 | −7.0 ± 1.0 | −11.0% |
| Polymarket, 30–70¢ | 1,971 | 52.5 | 52.0 | +0.5 ± 2.2 | −5.8% |
| Polymarket, score 75+, 30–70¢ | 489 | 56.4 | 52.5 | +3.9 ± 4.4 | −1.4% |

*"Fair %" is the win rate the market price implied. "Edge" is how much more often the bets won than the price implied, with its uncertainty margin.*

**What I learned:**

- **Whale picks were priced fairly.** Across ~17.8k settled bets, whales' side won 59.8% of the time, exactly what the price predicted. The market had already absorbed their information by the time anyone could follow.
- **Costs decide the outcome.** Spread, slippage and fees came to roughly 2–5¢ per bet (7–9% of the stake). An edge has to beat that before it's worth anything, and none did.
- **"Win most bets, lose money" is real.** The Score 90+ group won 69% of its bets and still lost, because it mostly bought favorites at high prices.
- **Limit orders made things worse.** Posting at the bid instead of buying at the ask *lost* more. The orders that got filled were disproportionately the losers (they won 56% vs. 70% for the ones that didn't fill), which is a textbook case of adverse selection.
- **Speed wasn't the bottleneck.** Simulating instant entry added ~0 on Kalshi and very little on the best Polymarket slice, so building a faster on-chain feed wouldn't have helped.
- The one slice worth watching (Polymarket, score 75+, 30–70¢) is within noise of break-even, so it isn't a proven edge.

The full scorecard output is in [`export/strategy_scorecard.txt`](export/strategy_scorecard.txt).

## Architecture

```
 Kalshi API ──┐                       ┌─> baseline.py  (per-market 7-day norms)
              ├─> collectors/ ─> SQLite ─> detect.py ─> score.py ─> alerts.py ─> terminal + dashboard
 Polymarket ──┘                       ├─> wallets.py / track.py  (wallet newness + track records)
                                      └─> outcomes.py ─> strategies.py / maker.py / speed.py  (paper trading + tests)
                                                                    │
                                                         web.py (Flask dashboard)
```

| Module | Role |
|---|---|
| `collectors/` | Paginated polling of both trade feeds, normalized into one schema |
| `baseline.py` | Rolling per-market statistics (median trade, p99, normal volume) |
| `detect.py`, `score.py` | 1/5/15-minute windows; the strongest window becomes the event |
| `wallets.py`, `track.py` | Wallet profiling and shrunk ROI / win-rate track records |
| `outcomes.py` | Post-alert price tracking and paper trades with realistic costs |
| `strategies.py` | Frozen forward-test scorecard with uncertainty margins |
| `maker.py`, `speed.py` | Experiments: limit-order entry and the value of faster detection |
| `web.py` + `templates/` | Dashboard |

All thresholds, weights and fees live in [`config.yaml`](config.yaml). The original design spec is in [`CONTEXT.md`](CONTEXT.md), and notes for AI assistants are in [`AGENTS.md`](AGENTS.md).

## Run it

You need Python 3.9+. No API keys or accounts are needed; both data sources are public.

1. **Get the code.** Click the green **Code** button at the top of this page. Choose **Download ZIP** and unzip it, or copy the link and run `git clone <link>`.
2. **Start it** from inside the project folder:

```bash
python3 start.py          # Windows: py start.py
```

That's it. The first run sets up its own environment, then the dashboard opens at http://localhost:8050. Press Ctrl-C to stop. On macOS you can also just double-click `Whale Hunter.command`.

**Or let an AI assistant do it.** Open the folder in Claude Code, Codex or Cursor and say *"set up and run this project."* [`AGENTS.md`](AGENTS.md) tells the assistant how to install it, run it in the background, check that it's healthy, and what a fresh install should look like.

| Command | What it does |
|---|---|
| `python3 start.py --check` | Set up and run the tests, then exit |
| `python3 start.py --no-browser` | Start without opening a browser tab |
| `python3 start.py --port 8060` | Use a different port |

**What to expect:** trades start flowing within seconds. The first alerts usually show up within a minute or two. Paper bets settle when their markets resolve, which takes hours to days.

> ⚠️ It stores every trade it sees in `data/whale.db`, about 3 GB/day. Trades older than `trades_retention_days` (21 by default) are deleted automatically.

<details>
<summary>Other commands</summary>

```bash
.venv/bin/python -m whale_hunter.track seed --period MONTH --top 200  # build proven-wallet watchlist
.venv/bin/python -m whale_hunter.track 0xWALLET                       # score one wallet
.venv/bin/python -m whale_hunter.outcomes                             # performance report
.venv/bin/python -m whale_hunter.strategies                           # strategy scorecard
.venv/bin/python -m whale_hunter.main                                 # collector only (no dashboard)
.venv/bin/python -m whale_hunter.web                                  # dashboard only
```
</details>

## How the scoring works

1. **Candidates:** markets with at least `min_window_notional` of flow in the last 15 minutes.
2. **Backfill:** a candidate with fewer than 10 prior trades gets its last 7 days fetched once, so it has a baseline.
3. **Score:** for 1/5/15-minute windows, each signal is measured against the market's own baseline on a log scale. The final score is the weighted mean × 100 over whichever signals can be evaluated.
4. **Wallets:** a single wallet with ≥ $5k directional flow that is ≥ 25× the market's median trade gets a profile lookup. NEW, LOW-HISTORY and REACTIVATED wallets get their own alert type.
5. **Track records:** wallets with ≥ 20 closed positions, ≥ $5k invested and shrunk ROI ≥ 5% are **PROVEN** and are alerted from $2k.
6. **Alerts:** stored at ≥ 40, printed at ≥ 75 (only with a sufficient baseline), with a cooldown per market and direction.

### Platform notes
- **Kalshi** doesn't expose trader identity or liquidity, so open-interest notional is used as the liquidity proxy. Multivariate parlay markets (`KXMVE*`) are skipped.
- **Polymarket**'s Data API lags ~2–3 minutes and its CDN caches for 5 minutes, so requests use a cache-busting parameter and windows are anchored to each market's latest trade.

## Disclaimer

This is a personal research project. All trading was simulated (paper trading), and nothing here is financial advice.

## Author

Built by **Isaiah Peebles**.

## License

[MIT](LICENSE)
