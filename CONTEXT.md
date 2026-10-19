# Prediction Market Whale Intelligence System

## 1. Project Mission

Build a real-time intelligence system that monitors prediction markets for statistically unusual trading activity, with an initial focus on Kalshi and Polymarket.

The system's primary purpose is to identify activity consistent with unusually large or aggressive traders ("whales"), and separately evaluate potentially informed behavior, before that activity becomes obvious from headline market prices alone.

The system must monitor markets broadly rather than relying on a manually selected watchlist.

Primary platforms:

- Kalshi
- Polymarket

The architecture should eventually allow additional prediction markets or betting exchanges to be added.

---

## 2. Core Principle

A large trade is not automatically unusual.

Whale detection must be relative to the normal behavior of the specific market.

For example:

Market A:
- $5,000,000 average daily volume
- $50,000 trade

This may be ordinary.

Market B:
- $20,000 average daily volume
- $50,000 trade

This is extraordinary.

Therefore, the system must detect **abnormal activity relative to historical and current market conditions**, not simply transactions exceeding a fixed dollar threshold.

---

## 3. Primary Questions

For every detected event, the system should answer:

### What happened?

Identify the trade, volume spike, order-book movement, liquidity event, or cluster of activity.

### How unusual is it?

Compare the event against historical behavior for that market and similar markets.

### What direction does it imply?

Determine whether capital is aggressively moving toward YES, NO, or another outcome.

### How much market impact occurred?

Measure whether the activity materially changed the implied probability.

### How confident are we that this represents meaningful whale activity?

Generate a Whale Score based on multiple independent signals, with a separate confidence assessment reflecting evidence quality and completeness. Evaluate historically predictive behavior separately through the Information Score.

---

## 4. Market Discovery

The system should continuously discover and maintain a registry of active markets.

Each market should contain normalized metadata such as:

```text
platform
market_id
event_id
title
description
category
outcomes
open_time
close_time
resolution_time
status
current_price
bid
ask
spread
liquidity
volume
volume_24h
open_interest
last_trade_time
```

Platform-specific fields should be retained separately.

Markets should also be classified into categories such as:

```text
Politics
Economics
Crypto
Sports
Technology
Weather
Geopolitics
Entertainment
Companies
Elections
Financial Markets
Other
```

---

## 5. Data Collection

The collector should capture the highest-frequency information practically available from each platform.

Important data includes:

```text
trades
price changes
volume changes
bid changes
ask changes
spread changes
order-book depth
liquidity
open interest
market creation
market closing
market resolution
```

Every observation should be timestamped.

Raw observations should be retained so detection algorithms can be changed later without losing historical data.

---

## 6. Historical Baselines

Every market needs a behavioral baseline.

The system should calculate rolling statistics over multiple windows.

Suggested windows:

```text
1 minute
5 minutes
15 minutes
1 hour
6 hours
24 hours
7 days
lifetime
```

Metrics should include:

```text
average trade size
median trade size
95th percentile trade size
99th percentile trade size
trade-size standard deviation

average volume per minute
average volume per 5 minutes
average volume per hour

median volume
volume volatility

average price movement
price volatility

average liquidity
average spread
average order-book depth
```

The baseline must update dynamically.

---

## 7. Relative Activity Detection

The system should calculate how unusual current activity is relative to the market's baseline.

Examples:

### Trade Size Ratio

```text
trade_size / median_trade_size
```

Example:

```text
median trade = $250
observed trade = $25,000

ratio = 100x
```

This is substantially more informative than simply reporting "$25,000 trade."

---

## 8. Volume Spike Detection

Calculate abnormal volume across several windows.

Example:

```text
current_5m_volume / historical_average_5m_volume
```

Example:

```text
normal 5-minute volume = $4,000
current 5-minute volume = $160,000

Volume Spike = 40x
```

Also calculate percentile and statistical anomaly measurements.

Potential techniques:

```text
Z-score
robust Z-score
percentile ranking
EWMA deviation
median absolute deviation
```

Do not depend exclusively on standard deviation because prediction-market activity may be highly non-normal.

---

## 9. Price Impact

Large capital becomes more interesting when it materially changes market probability.

Measure:

```text
price_before
price_after
absolute_change
percentage_change
probability_point_change
time_to_price_change
```

Example:

```text
YES: 41% → 53%

Change: +12 probability points
```

A large transaction with little price impact may represent deep liquidity.

A similarly sized transaction that moves probability dramatically can be much more significant.

---

## 10. Liquidity-Adjusted Trade Size

Compare capital entering the market with available liquidity.

Example metric:

```text
Liquidity Impact Ratio =
trade_notional / visible_liquidity
```

Example:

```text
trade = $80,000
available relevant liquidity = $120,000

impact ratio = 66.7%
```

This should generate a much stronger signal than an $80,000 trade entering a market with $10 million of liquidity.

---

## 11. Aggressive Trading Detection

Distinguish passive liquidity from aggressive activity where possible.

Important behaviors:

```text
repeated buying at the ask
repeated selling at the bid
multiple price levels consumed
rapid consecutive trades
spread crossing
sudden depletion of order-book depth
```

Aggressive execution is more informative than merely placing a large resting order.

---

## 12. Trade Clustering

A whale may intentionally split a large position into many smaller transactions.

Therefore:

```text
$50,000
```

and

```text
$5,000
$5,000
$5,000
$5,000
$5,000
$5,000
$5,000
$5,000
$5,000
$5,000
```

within a short period should potentially be treated as equivalent activity.

Create rolling trade clusters using:

```text
market
direction
price proximity
time proximity
trade size
execution behavior
```

Suggested windows:

```text
10 seconds
30 seconds
1 minute
5 minutes
15 minutes
```

---

## 13. Sustained Accumulation

Not every whale moves immediately.

Detect persistent directional accumulation.

Example:

```text
10:01 YES +$8k
10:04 YES +$12k
10:09 YES +$9k
10:14 YES +$17k
10:20 YES +$15k
```

Individually these may not trigger an extreme alert.

Together they represent:

```text
$61,000 directional accumulation
```

The system should therefore calculate cumulative directional flow.

---

## 14. Order-Book Shock

Track changes in available liquidity.

Examples:

```text
large ask wall disappears
large bid appears
multiple ask levels consumed
spread suddenly widens
depth collapses
depth rapidly replenishes
```

Order-book changes should not automatically be considered executed whale activity because orders can be canceled.

Executed trades should generally receive greater confidence than resting orders.

---

## 15. Whale Detection Score

Create a normalized score:

```text
0–100 Whale Score
```

Possible inputs:

```text
Trade Size Anomaly
Volume Anomaly
Liquidity Impact
Price Impact
Directional Aggression
Trade Clustering
Sustained Accumulation
Order-Book Impact
Cross-Market Confirmation
Historical Rarity
```

Example conceptual weighting:

```text
Trade Size Anomaly        20%
Volume Anomaly            15%
Liquidity Impact          15%
Price Impact              15%
Aggressive Execution      10%
Trade Clustering          10%
Sustained Accumulation     5%
Order-Book Shock           5%
Cross-Market Confirmation  5%
```

Weights should eventually be calibrated from observed data rather than treated as permanent constants.

---

## 16. Alert Severity

Suggested classifications:

```text
0–39
NORMAL

40–59
ELEVATED

60–74
UNUSUAL

75–89
WHALE ACTIVITY

90–100
EXTREME WHALE ACTIVITY
```

The system must explain WHY a score was generated.

Never display only:

```text
Whale Score: 87
```

Instead display:

```text
WHALE ACTIVITY — Score 87/100

Market:
Will X happen?

Direction:
YES

Detected:
$186,400 directional volume over 7 minutes

Why unusual:
31.2x normal 5-minute volume
99.8th percentile historical activity
largest directional cluster in 18 days
YES probability moved 43% → 57%
visible ask liquidity fell 64%
87% of detected aggressive flow favored YES
```

Explainability is a core requirement.

---

## 17. Historical Rarity

Every alert should attempt to contextualize the event historically.

Examples:

```text
Largest 5-minute volume spike in 30 days

99.7th percentile volume event

14x larger than median activity

Largest YES-side accumulation recorded for this market

Top 0.4% of activity bursts
```

This is one of the strongest ways to establish that something genuinely unusual occurred.

---

## 18. Market Regime Awareness

Markets naturally behave differently at different stages.

Activity often increases near:

```text
elections
economic releases
sports starts
earnings
deadlines
market expiration
major news events
resolution
```

The anomaly model should therefore consider time-to-resolution.

A $100,000 spike three months before resolution may be extraordinary.

The same activity minutes before resolution may be normal.

---

## 19. Cross-Market Intelligence

One of the most important advanced features is detecting related activity across multiple markets.

Example:

```text
Market A:
Candidate X wins election

Market B:
Party X controls Senate

Market C:
Candidate X wins State Y
```

If unusual capital simultaneously moves all three markets in a logically consistent direction, confidence should increase.

Create relationships between markets using:

```text
shared entities
shared events
semantic similarity
logical dependency
category
expiration timing
```

---

## 20. Cross-Platform Confirmation

The same underlying event may trade on both Kalshi and Polymarket.

Where equivalent markets can be identified, compare:

```text
Kalshi probability
Polymarket probability
Kalshi volume
Polymarket volume
price movement timing
volume spike timing
```

Example:

```text
POLYMARKET
YES 44% → 51%
abnormal volume detected

3 minutes later:

KALSHI
YES 45% → 50%
abnormal volume detected
```

This should be considered stronger evidence of broad information-driven repricing than isolated activity on one venue.

---

## 21. Lead/Lag Analysis

Record which venue or related market moves first.

Over time the system should be capable of answering:

```text
Does Polymarket usually react before Kalshi?

Does Kalshi lead economic markets?

Which market tends to price information first?

How long does price discovery propagate between related markets?
```

This turns the system from a whale alert service into a broader prediction-market intelligence platform.

---

## 22. Entity/Wallet Intelligence

Where publicly available platform data allows participant or wallet-level attribution, maintain behavioral profiles.

Potential statistics:

```text
wallet/account identifier
markets traded
estimated volume
average position size
directional tendencies
historical activity
markets entered early
price movement following activity
resolution performance where inferable
```

Do not assume that a large wallet is informed.

Separate:

```text
LARGE TRADER
```

from:

```text
HISTORICALLY INFORMATIVE TRADER
```

These are fundamentally different concepts.

---

## 23. New Wallet & Potentially Informed Trader Detection

### New Wallet Intelligence

The system should explicitly monitor newly created, newly funded, previously inactive, or historically low-activity wallets/accounts that suddenly establish unusually large prediction-market positions.

A newly created wallet making a large trade must NOT automatically be classified as an informed trader.

Instead, wallet age should be treated as one component of a broader behavioral anomaly model.

The objective is to identify situations where multiple unusual characteristics occur simultaneously.

Example:

```text
NEW WALLET
     ↓
LARGE FUNDING EVENT
     ↓
LITTLE OR NO PREVIOUS TRADING HISTORY
     ↓
LARGE POSITION IN A SPECIFIC MARKET
     ↓
HIGHLY DIRECTIONAL POSITION
     ↓
AGGRESSIVE EXECUTION
     ↓
SIGNIFICANT PRICE IMPACT
```

This should generate substantially more interest than a new wallet simply making an ordinary trade.

---

### Wallet Classification

Where technically possible, classify observed participants into behavioral categories.

Suggested classifications:

```text
NEW WALLET
NEWLY FUNDED WALLET
LOW-HISTORY WALLET
DORMANT WALLET
REACTIVATED WALLET
ACTIVE TRADER
LARGE TRADER
WHALE
REPEAT WHALE
HIGH-SIGNIFICANCE WALLET
HISTORICALLY PREDICTIVE WALLET
```

These classifications are descriptive.

The system must not claim that a participant possesses private or inside information.

---

### New Wallet Signals

Important features include:

```text
wallet_age
first_seen_timestamp
first_prediction_market_activity
number_of_previous_markets
number_of_previous_trades
historical_volume
recent_funding
estimated_funding_amount
position_size
position_concentration
directional_concentration
execution_aggressiveness
price_impact
liquidity_impact
```

Where wallet creation itself cannot be determined reliably, use:

```text
FIRST SEEN
```

rather than assuming:

```text
WALLET CREATED
```

The system must distinguish between observable facts and inferred characteristics.

---

### New Wallet Large Position Detection

A particularly important signal is a new or low-history wallet establishing a position dramatically larger than normal activity in the target market.

Example:

```text
Wallet age:
4 hours

Previous prediction-market trades:
0

Position:
$185,000 YES

Market median trade:
$420

Position / median trade:
440x

Normal 5-minute volume:
$7,500

Current 5-minute volume:
$201,000
```

This should generate a high-significance wallet alert.

However:

```text
NEW WALLET + LARGE POSITION
```

is evidence of unusual behavior, NOT evidence of private information.

---

### Capital Concentration

Measure how concentrated observable wallet activity is.

Example:

```text
Observable wallet capital:
$300,000

Position:
$260,000

Observable concentration:
86.7%
```

A participant placing a substantial portion of observable capital into one prediction may deserve greater attention than a large diversified participant making the same trade.

Potential metric:

```text
Observable Position Concentration =
Position Notional / Observable Wallet Capital
```

Treat this carefully because observable wallet capital may not represent the participant's complete financial position.

---

### Market Concentration

Measure whether the participant is trading broadly or targeting a specific event.

Example:

```text
Wallet prediction-market volume:

Market A: $285,000
Market B: $4,000
Market C: $2,000
```

Market A represents approximately 98% of observed prediction-market activity.

This should increase significance.

---

### Directional Concentration

Measure whether activity strongly favors one outcome.

Example:

```text
YES-directed activity:
$240,000

NO-directed activity:
$12,000

YES concentration:
95.2%
```

Highly concentrated directional exposure can represent stronger conviction than mixed activity.

---

### Dormant Wallet Reactivation

New wallets are not the only interesting behavior.

Monitor previously inactive wallets that suddenly become active.

Example:

```text
Last activity:
143 days ago

Historical median trade:
$1,800

New position:
$175,000

Direction:
YES
```

A dormant participant suddenly making an unusually large directional trade should potentially receive similar treatment to a newly observed wallet.

---

### First-Trade Anomaly

Track whether a participant's first observed prediction-market trade is itself extraordinary.

Example:

```text
Previous observed trades:
0

First observed position:
$325,000

Market median trade:
$700

Multiple:
464x
```

This should be considered a strong anomaly signal. Position-to-median-trade comparisons describe aggregate exposure relative to individual trade size; they must be labeled separately from a single-trade anomaly.

---

### Wallet Funding Events

Where public data permits, monitor significant funding immediately preceding prediction-market activity.

Potential pattern:

```text
Wallet receives large funding
        ↓
Short delay
        ↓
Capital enters prediction market
        ↓
Large directional position established
```

Track:

```text
funding_timestamp
estimated_funding_amount
time_from_funding_to_trade
position_size_relative_to_funding
funding_source
```

Funding relationships should be treated as analytical evidence rather than definitive proof that two wallets share an owner.

---

### Wallet Relationship Graph

Where public blockchain information allows it, construct a graph of relationships between wallets.

Potential relationships include:

```text
funded_by
transferred_to
transferred_from
shared_counterparty
repeated_funding_source
similar_market_activity
temporally correlated activity
```

The objective is to detect possible wallet clusters.

Example:

```text
Funding Wallet
      │
 ┌────┼────┐
 ▼    ▼    ▼
W1   W2   W3
 │    │    │
YES  YES  YES
```

If three newly observed wallets funded through related sources simultaneously establish similar positions, the system should consider whether this represents coordinated or related activity.

Do NOT automatically assume common ownership.

---

### Split-Wallet Detection

A sophisticated participant may distribute a position across multiple wallets.

Therefore, the system should look for:

```text
similar funding timing
similar funding sources
same target market
same direction
similar execution timing
similar trade sizes
repeated synchronized behavior
```

Example:

```text
Wallet A: $45,000 YES
Wallet B: $52,000 YES
Wallet C: $48,000 YES
Wallet D: $51,000 YES
```

within several minutes may be more significant collectively than individually.

Create a:

```text
POSSIBLE WALLET CLUSTER
```

classification when sufficient evidence exists.

---

## 24. Information Score

Create a second major scoring system independent from the Whale Score.

```text
Information Score: 0–100
```

The two scores answer different questions.

### Whale Score

```text
How abnormal is the capital/activity?
```

### Information Score

```text
How strongly does the observed behavior resemble activity
that has historically preceded subsequent market repricing?
```

These concepts MUST remain separate.

A massive trade can have:

```text
Whale Score: 97
Information Score: 31
```

while another event might have:

```text
Whale Score: 76
Information Score: 91
```

The second event could potentially be more interesting from a market-intelligence perspective.

---

### Information Score Inputs

Potential features:

```text
wallet age / first-seen recency
previous trading history
historical wallet performance
position concentration
directional concentration
trade-size anomaly
volume anomaly
execution aggressiveness
price impact
liquidity impact
historical timing before subsequent repricing
cross-market confirmation
cross-platform confirmation
wallet-cluster behavior
historical rarity
```

Weights should ultimately be determined through historical validation.

Do NOT permanently assign arbitrary weights without backtesting.

---

### Reconciliation with the Informed Trader Score

The original **Informed Trader Score** concept is retained as the historical participant-performance component of the **Information Score**, rather than a third major public score. Where attribution is technically possible, it measures whether a participant's historical activity has preceded correct market repricing.

Its original metrics remain applicable:

```text
average subsequent 5m movement
average subsequent 1h movement
average subsequent 24h movement
entry timing
market resolution accuracy
risk-adjusted historical performance
sample size
```

These participant-level statistics inform the event-level Information Score alongside current behavioral evidence. A new or low-history wallet has an unknown historical-performance component; missing history must not be interpreted as poor performance or invented predictive ability.

Live scoring must use only information available at the detection timestamp. Subsequent price movement and final resolution are historical evaluation targets, not inputs from the current event's future. Cross-market or cross-platform confirmation arriving later may update an alert, with the update timestamp retained.

### Historical Wallet Performance

For wallets with sufficient history, determine what historically happened after their trades.

Measure:

```text
5-minute subsequent price movement
30-minute subsequent price movement
1-hour subsequent price movement
6-hour subsequent price movement
24-hour subsequent price movement
final market resolution
```

Example:

```text
Wallet enters YES at 41%

5 minutes later:
42%

1 hour later:
47%

6 hours later:
53%

24 hours later:
61%

Resolution:
YES
```

Store these observations for future analysis.

---

### Wallet Predictive Performance

Potential wallet-level statistics:

```text
total observed trades
total markets traded
average trade size
median trade size

5m directional accuracy
30m directional accuracy
1h directional accuracy
6h directional accuracy
24h directional accuracy

average subsequent price movement
median subsequent price movement

resolution accuracy
sample size
```

Performance metrics should include minimum sample-size requirements.

A wallet that correctly precedes two market movements should NOT automatically receive the same confidence as one with dozens of historically predictive observations.

---

### Signal Decay

Measure how quickly the apparent information advantage disappears.

Example:

```text
T+0      Whale enters
T+5m     +1 probability point
T+30m    +4 points
T+1h     +9 points
T+6h     +10 points
T+24h    +10 points
```

This suggests most repricing occurred within approximately six hours.

Different market categories may exhibit different signal-decay profiles.

---

### New Wallet + Abnormal Position Signal

Create a dedicated composite detector for:

```text
NEW OR LOW-HISTORY PARTICIPANT
            +
ABNORMALLY LARGE POSITION
            +
HIGH DIRECTIONAL CONCENTRATION
            +
AGGRESSIVE EXECUTION
```

This should be one of the system's high-priority signals.

Example alert:

```text
🚨 HIGH-SIGNIFICANCE NEW WALLET

Market:
Will [EVENT] happen?

Platform:
Polymarket

Direction:
YES

Position:
$287,400

First Seen:
3 hours ago

Previous Observed Markets:
0

Market Median Trade:
$640

Position / Median Trade:
449x

5-Minute Volume:
38x normal

Directional Concentration:
96% YES

Probability:
34% → 41%

Nearby Ask Liquidity Consumed:
61%

Whale Score:
96 / 100

Information Score:
84 / 100

Classification:
HIGH-SIGNIFICANCE NEW-WALLET ACTIVITY

Interpretation:
A recently observed participant established an extremely
large and concentrated directional position relative to
normal activity in this market.

This represents statistically unusual behavior but does
not establish that the participant possesses private
information.
```

---

## 25. Wallet Significance Score

Optionally maintain an internal:

```text
Wallet Significance Score
```

This measures how closely a participant should be monitored independent of any single trade.

Possible components:

```text
historical position size
historical anomaly frequency
historical predictive performance
market concentration
execution behavior
cross-market behavior
sample size
recent activity
```

Example:

```text
Wallet:
0x...

Wallet Significance:
91 / 100

Observed Markets:
37

Historical Whale Events:
14

1-Hour Directional Accuracy:
71%

6-Hour Directional Accuracy:
74%

Median Subsequent 6H Move:
+7.4 probability points
```

The system should avoid presenting historical association as guaranteed future predictive ability.

---

## 26. Signal Combination

The strongest alerts should generally arise from combinations of independent evidence rather than one variable.

Example:

```text
New Wallet                    +
Large Position                +
Position Concentration        +
Volume Anomaly                +
Aggressive Execution          +
Order-Book Consumption        +
Price Impact                  +
Related Market Movement       +
Historical Wallet Performance
```

is substantially stronger than:

```text
Large Trade
```

alone.

The system should explicitly reward independent confirmation.

---

## 27. Important Counterexamples

The detection engine must consider benign explanations.

A new wallet making a large trade could represent:

```text
an experienced trader using a new wallet
capital moved from another wallet
arbitrage
hedging
market making
portfolio rebalancing
cross-platform exposure
a participant reacting to public information
multiple people controlled through one funding source
```

Therefore, alerts should describe OBSERVED BEHAVIOR rather than claim intent.

Prefer:

```text
High-significance new-wallet activity detected.
```

Avoid:

```text
Insider detected.
```

---

## 28. Core Analytical Distinction

The system must preserve the following hierarchy:

```text
LARGE TRADE
     ↓
WHALE ACTIVITY
     ↓
STATISTICALLY UNUSUAL WHALE ACTIVITY
     ↓
HISTORICALLY PREDICTIVE ACTIVITY
     ↓
POTENTIALLY INFORMATION-ADVANTAGED ACTIVITY
```

Each level requires additional evidence.

The system must never automatically jump from:

```text
Large trade
```

to:

```text
Informed trader
```

without supporting historical and behavioral evidence.

---

## 29. False Positive Reduction

Common false positives include:

```text
market opening
market closing
resolution activity
scheduled news releases
thin liquidity
single erroneous trades
arbitrage
market-maker inventory management
liquidity migrations
platform outages
API anomalies
```

The detector should identify and label these situations rather than blindly calling them whales.

---

## 30. Whale vs Market-Wide News

A major challenge is distinguishing:

```text
INFORMED / UNUSUAL CAPITAL
```

from:

```text
EVERYONE REACTING TO PUBLIC NEWS
```

A broad burst containing many independent trades after obvious news is different from concentrated capital appearing before widespread repricing.

Useful measurements include:

```text
trade concentration
number of unique participants where available
cluster concentration
timing
cross-market timing
price impact
news-event proximity
```

---

## 31. Confidence Model

Every alert should contain both:

```text
Whale Score
Information Score where evaluable
Confidence
```

Example:

```text
Whale Score: 92/100
Confidence: HIGH
```

Confidence should depend partly on data completeness. Report score availability and confidence separately for activity detection and information significance. Missing participant attribution need not reduce confidence in directly observed market anomalies, but limits wallet-specific conclusions. An Information Score is not a probability that a trader has private information.

Example:

If wallet identity is unavailable:

```text
Whale Score: 86
Confidence: MEDIUM

Reason:
Activity is extremely abnormal, but trader identity cannot be confirmed.
```

This prevents the system from pretending it knows more than the underlying data supports.

---

## 32. Dashboard

The primary dashboard should rank markets by abnormal activity.

Example:

| Rank | Market | Platform | Direction | Whale Score | Volume Spike | Price Move |
|---|---|---|---|---:|---:|---:|
| 1 | Market A | Polymarket | YES | 94 | 37x | +14 pts |
| 2 | Market B | Kalshi | NO | 89 | 22x | -9 pts |
| 3 | Market C | Polymarket | YES | 78 | 11x | +5 pts |

Information Score and its evidence/confidence should also be available for ranking where evaluable; unavailable scores should be labeled explicitly.

Additional views:

```text
Live Whale Feed
Extreme Activity
Market Explorer
Cross-Platform Divergence
Whale/Wallet Profiles
New & Reactivated Wallets
Possible Wallet Clusters
Information Score Signals
Category Heatmap
Historical Alerts
Related Markets
```

---

## 33. Alert Format

Example:

```text
🚨 EXTREME ACTIVITY DETECTED

Market:
Will [EVENT] happen?

Platform:
Polymarket

Direction:
YES

Whale Score:
94 / 100

Activity:
$427,000 directional volume detected in 11 minutes

Historical Comparison:
42.6x normal 15-minute volume
99.96th percentile
Largest activity burst in 60 days

Probability:
38% → 56%

Price Impact:
+18 probability points

Liquidity:
71% of nearby ask liquidity consumed

Flow:
91% YES-directed

Cross-Market:
Related Kalshi market moved +7 points 4 minutes later

Interpretation:
Extremely abnormal directional capital entered the market and materially repriced probability.

Confidence:
HIGH
```

---

## 34. Database Architecture

Suggested logical datasets:

```text
markets
market_snapshots
trades
orderbook_snapshots
volume_intervals
market_relationships
wallets
wallet_activity
wallet_funding_events
wallet_relationships
wallet_clusters
wallet_performance
information_scores
signal_outcomes
activity_clusters
anomaly_scores
alerts
platform_status
resolutions
```

Do not store only calculated alerts.

Store raw market data whenever practical so detection models can be reconstructed and backtested.

---

## 35. Detection Pipeline

Conceptual pipeline:

```text
Kalshi API ───────┐
                  │
                  ├── Data Collectors
Polymarket API ──┘
                        │
                        ▼
                 Normalization Layer
                        │
                        ▼
                   Raw Storage
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
      Baseline Engine       Relationship Engine
             │                     │
             └──────────┬──────────┘
                        ▼
                 Anomaly Engine
                        │
                        ▼
                Clustering Engine
                        │
                        ▼
          Whale + Information Scoring
                        │
                        ▼
               Alert Generation
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
        Dashboard               Notifications
```

---

## 36. Backtesting

Both scoring systems must be backtestable. Replay historical events using only data available at each detection timestamp, and evaluate later outcomes separately. Calibrate weights on historical training data and assess them on held-out periods. Account for market regime, sample size, correlated events, and the difference between immediate execution impact and subsequent repricing.

For historical anomaly events determine:

```text
What happened after 5 minutes?
What happened after 30 minutes?
What happened after 1 hour?
What happened after 6 hours?
What happened after 24 hours?
What was the final market resolution?
```

This allows the project to determine whether detected whale activity actually contains predictive information.

Critical distinction:

```text
unusual activity ≠ predictive activity
```

The system must measure whether signals historically predicted subsequent repricing rather than assuming they did.

---

## 37. Signal Performance

Track performance of alerts.

Metrics:

```text
alerts generated
false-positive rate
average subsequent price movement
median subsequent price movement
directional accuracy
resolution accuracy
performance by Whale Score
performance by Information Score
performance by wallet classification
performance by history/sample-size cohort
performance by category
performance by platform
performance by anomaly type
```

Eventually this allows statements such as:

```text
Whale Score 90+ events historically preceded same-direction
price movement within 6 hours 68% of the time.
```

Only generate such claims when supported by sufficient historical observations.

---

## 38. Development Priorities

Build the project incrementally.

### Phase 1 — Data

Connect Kalshi and Polymarket.

Discover markets.

Collect:

```text
prices
trades
volume
liquidity
order books
open interest where available
```

Store historical observations.

### Phase 2 — Anomaly Detection

Implement:

```text
volume spike detection
trade-size anomaly detection
price movement detection
liquidity-adjusted activity
historical percentile ranking
```

### Phase 3 — Whale Engine

Add:

```text
trade clustering
directional accumulation
aggressive execution detection
Whale Score
confidence score
alerts
```

### Phase 4 — Intelligence

Add:

```text
cross-market relationships
Kalshi ↔ Polymarket matching
lead/lag analysis
wallet profiling where possible
historical trader behavior
new-wallet and dormant-wallet detection
funding events and possible wallet clusters
Information Score
optional Wallet Significance Score
```

### Phase 5 — Validation

Backtest alerts.

Measure:

```text
predictive value
false positives
signal decay
optimal thresholds
category differences
platform differences
```

Use results to recalibrate Whale Score and Information Score weights. Validate Information Score performance separately from capital/activity abnormality.

---

## 39. Engineering Principles

The system should follow these rules:

1. Never call something a whale solely because a dollar threshold was exceeded.

2. Always compare activity against the market's historical baseline.

3. Prefer executed activity over unexecuted resting orders.

4. Separate abnormal activity from predictive activity.

5. Clearly distinguish observed facts from inferred behavior.

6. Never claim a trader possesses inside information.

7. Always provide evidence explaining anomaly classifications.

8. Preserve raw data for future backtesting.

9. Make thresholds configurable rather than hard-coded.

10. Treat data quality and missing information explicitly.

11. Use multiple independent signals before assigning high-confidence whale classifications.

12. Optimize first for detection accuracy and explainability, not automated trading.

---

## 40. Ultimate Goal

The final product should function as a prediction-market intelligence terminal capable of answering:

```text
Where is unusually large capital moving right now?

How abnormal is that activity?

Which direction is the money moving?

Are newly observed wallets establishing unusually large positions?

Are dormant wallets suddenly becoming active?

Are multiple related wallets moving simultaneously?

How concentrated is the capital?

How aggressively is it being deployed?

Did it materially change market probabilities?

Is similar activity appearing in related markets?

Is another prediction-market platform reacting?

Did Kalshi or Polymarket move first?

Has this participant historically preceded market repricing?

Has activity like this historically predicted further repricing?

How quickly does the informational advantage disappear?

Is this likely one concentrated participant or broad market activity?

Is this likely ordinary whale activity or a historically significant signal?

Which markets currently contain the strongest abnormal signals?
```

The objective is to build a system capable of identifying, ranking, explaining, and historically validating unusual flows of capital across prediction markets.

The system should transform raw prediction-market activity into measurable, explainable intelligence rather than simply displaying large transactions.
