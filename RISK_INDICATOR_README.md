# Risk On / Off Indicator

A composite market sentiment indicator built for the **2-8 week investment horizon**. Combines six asset class signals into a single z-score, updated daily as part of the ETF Dashboard refresh cycle.

Live at: https://etf-dashboard-3tfz.onrender.com/risk-indicator

---

## What It Does

Each evening after market close, the indicator fetches adjusted closing prices for 12 tickers, computes a 252-day z-score for each of six components, and combines them into a single weighted composite score. The score determines a signal — Risk On, Lean Risk On, Neutral, Lean Risk Off, or Risk Off — which is displayed as a gauge with a needle and embedded as a badge in the ETF dashboard header.

A rolling accuracy tracker records each day's signal, then resolves it 10 trading days later by comparing the prediction to SPY's actual 10-day return.

---

## The Six Components

### Why six components rather than one?

Any single indicator can be gamed by the market regime it wasn't designed for. Equity ratios miss geopolitical crises. Currency signals become ambiguous when both safe-haven and risk currencies strengthen simultaneously. Credit spreads are slow but lead equity by days. The composite is designed so that each component fills a gap left by the others.

---

### 1. S&P Long/Short Ratio — SPY / SH — Weight: 20%

**What it is:** The price of SPY (SPDR S&P 500 ETF, long) divided by SH (ProShares Short S&P 500, inverse). When investors are bullish, SPY rises and SH falls, so the ratio rises faster than SPY alone.

**Why ratio, not SPY price?** The ratio captures momentum and direction of sentiment rather than absolute price level. A market at SPY 560 that has been flat for a month reads very differently from one that rose from 500 — the ratio's z-score distinguishes these.

**Why SPY/SH instead of SPXL/SPXS?** The 3x leveraged ETFs (SPXL/SPXS) decay against each other in choppy, mean-reverting markets due to daily rebalancing. Over a 252-day window, this drift distorts the z-score baseline in ways that have nothing to do with risk sentiment. SPY/SH has no leverage and no decay problem.

---

### 2. Nasdaq Long/Short Ratio — TQQQ / SQQQ — Weight: 15%

**What it is:** TQQQ (3x leveraged Nasdaq-100 long) divided by SQQQ (3x leveraged Nasdaq-100 short).

**Why use leveraged ETFs here when SPY/SH uses unlevered?** The Nasdaq component is intentionally more sensitive. Technology and growth stocks are the most risk-sensitive part of the market and often lead the broader index by a few days. The amplification from 3x leverage makes the ratio respond faster to shifting sentiment, which is valuable as an early-warning signal. The drift problem is less severe here because TQQQ and SQQQ drift in opposite directions and tend to cancel each other out in the ratio over short windows. The z-score normalization also absorbs much of the long-run drift.

**Why 15% weight instead of 20%?** Tech sentiment is a leading signal but also noisier. It gets slightly less weight than the broad equity component to avoid overreacting to short-lived tech-specific moves.

---

### 3. Credit vs Treasury Ratio — HYG / IEI — Weight: 25%

**What it is:** HYG (iShares High Yield Bond ETF) divided by IEI (iShares 3-7 Year Treasury Bond ETF). When investors are confident, they accept the credit risk of junk bonds over safe Treasuries, pushing HYG up relative to IEI. When fear rises, they flee to Treasuries, collapsing the ratio.

**Why does this get the highest weight?**

Credit markets are dominated by insurance companies, pension funds, and large bank treasury desks — institutional investors who manage enormous positions, have deep research teams, and move deliberately. They rebalance credit exposure *before* equity exposure because credit positions are harder to unwind quickly. As a result, credit spread widening tends to precede equity selloffs by 3-10 trading days.

During the April 2025 tariff tantrum, HY spreads began widening in mid-March — weeks before the Liberation Day crash. The equity components of the indicator were already signaling caution by late March due to the credit signal pulling the composite lower.

**Why HYG/IEI ratio rather than the spread directly?** The spread (yield difference) requires two yield calculations and is less immediately responsive to intraday flows. The ETF price ratio captures the same information in a form that can be z-scored consistently with all other components.

---

### 4. Copper vs Gold Ratio — CPER / GLD — Weight: 20%

**What it is:** CPER (US Copper Index Fund) divided by GLD (SPDR Gold Shares). Copper is the most economically sensitive industrial commodity — a proxy for global manufacturing activity, construction, and capital expenditure. Gold is the purest fear asset, rising when investors seek safety. The ratio rises in risk-on environments (copper outperforms) and falls in risk-off environments (gold outperforms).

**Why is this better than just watching SPY?** The copper/gold ratio is **regime-independent** in a way that equity ratios are not. Consider two scenarios:

- *Trade war* (April 2025): Tariffs threaten global manufacturing. Copper falls on demand concerns. Gold rises as investors hedge dollar risk. The ratio collapses — risk-off signal.
- *Geopolitical military conflict* (Iran war, 2026): Oil spikes. Copper falls on global growth fears. Gold spikes on geopolitical safe-haven demand. The ratio again collapses — risk-off signal.

In both cases, copper/gold gives a consistent signal even though the underlying cause is completely different. Equity ratios and currency signals behave differently across these two regimes, but copper/gold is reliable in both.

**Why CPER rather than copper futures?** CPER is available as a Tiingo ticker, making it consistent with the rest of the pipeline. DBB (DB Base Metals ETF) is an acceptable substitute if CPER is not available on your Tiingo plan.

---

### 5 & 6. Safe-Haven Currency ETFs — FXY and FXF — Weight: 7.5% each (15% combined)

**What they are:**
- FXY: Invesco CurrencyShares Japanese Yen Trust. Rises when the yen strengthens.
- FXF: Invesco CurrencyShares Swiss Franc Trust. Rises when the franc strengthens.

Both are **inverted** before entering the composite — a rising FXY or FXF z-score means the currency is appreciating (risk-off), so inverting it makes the component negative (consistent with other components where negative = risk-off).

**Why two currencies instead of one?**

USD/JPY alone was used in the original design but performed poorly during the Iran war (March-April 2026). The reason: in a geopolitical crisis, the US dollar often strengthens as a global safe-haven *simultaneously* with the yen strengthening. When both move together, USD/JPY barely moves at all — the two safe-haven demands cancel each other out. The signal goes quiet exactly when you need it.

The Swiss franc is different. Switzerland is geopolitically neutral, has no military alliances, and holds enormous gold reserves. In a geopolitical crisis, money flows into CHF even when it also flows into USD — making FXF rise (franc strengthens) even when FXY is muted by dollar strength.

Combining FXY and FXF creates a currency basket that captures both carry-trade unwinding (yen) and geopolitical flight-to-safety (franc). One or the other almost always moves in the expected direction.

**Why 7.5% each rather than one at 15%?** Splitting the weight acknowledges that no single currency is reliable in all regimes. Each gets half the allocation so that a period where one is muted (as USD/JPY was in March 2026) only costs 7.5 percentage points of influence rather than the full 15%.

---

### 7. VIX Term Structure — VIXY / VIXM — Weight: 5%

**What it is:** VIXY (ProShares VIX Short-Term Futures ETF, tracks near-term VIX) divided by VIXM (ProShares VIX Mid-Term Futures ETF, tracks medium-term VIX). This is **inverted** — a high VIXY/VIXM ratio means near-term fear massively exceeds medium-term expectations, which is a panic spike rather than a sustained concern.

**Why is this primarily a reversal signal rather than a directional one?**

When VIXY >> VIXM (extreme near-term panic), the futures curve is in steep backwardation. Historically this condition — reflected in the z-score dropping below -2.0 — has coincided with market bottoms rather than the beginning of sustained downtrends. The April 9, 2025 day when the tariff pause was announced is a textbook example: VIX had spiked to 52, the term structure z-score was well below -2.0, and markets surged 9.5% that day.

Because this component is more useful as a reversal alert than a directional signal, it receives only 5% weight. The separate "VIX reversal alert" banner fires independently when the term structure z-score drops below -2.0, regardless of the composite.

---

## The Z-Score Mechanic

Every component is converted to a z-score before being combined:

```
z = (today's value - 252-day trailing mean) / 252-day trailing standard deviation
```

**Why z-scores?**

Without normalization, the components are on completely incomparable scales. The SPY/SH ratio sits around 39-42. The HYG/IEI ratio sits around 1.10-1.20. You cannot simply average these numbers — the SPY/SH ratio would dominate the composite by sheer magnitude.

The z-score converts every component to the same language: *how many standard deviations above or below its own past year average is today's reading?* A z-score of +1.5 always means "elevated relative to the past year" regardless of whether the underlying series is measured in ratio points, currency units, or ETF prices.

**What the window length means**

The 252-day window (one trading year) means the indicator is always asking: "how does today compare to the past year?" This is intentional. A reading that would have been extreme in 2021 (low-volatility bull market) may be ordinary in a high-volatility regime. Using a rolling 1-year window means the indicator self-calibrates to the current volatility environment.

**What the thresholds mean statistically**

In a normal distribution:
- ±0.25 is roughly the 40th/60th percentile — "slightly above or below average"
- ±1.00 is roughly the 16th/84th percentile — "one standard deviation from average"

So "Lean Risk On/Off" captures readings that are somewhat elevated but not extreme. "Risk On/Off" captures genuinely unusual readings — the top or bottom 16% of the historical distribution.

---

## Composite Calculation

```
composite = sum(weight_i x zscore_i) / sum(weight_i for valid components)
```

The denominator renormalizes if any component is unavailable (ticker not on your Tiingo plan, fewer than 60 days of data). This means the indicator degrades gracefully — losing one component shifts weight to the remaining five rather than producing a misleading result.

**Signal thresholds:**

| Composite | Signal | What It Means |
|-----------|--------|---------------|
| > +1.00 | Risk On | All major components elevated; strong risk appetite |
| +0.25 to +1.00 | Lean Risk On | Moderate risk appetite; favorable but not extreme |
| -0.25 to +0.25 | Neutral | Mixed signals; no clear regime |
| -1.00 to -0.25 | Lean Risk Off | Moderate stress; caution warranted |
| < -1.00 | Risk Off | Multiple components in stress; defensive posture |

---

## The VIX Reversal Alert

Separate from the composite score, the indicator monitors the VIXY/VIXM z-score after inversion. When it drops below -2.0 — meaning near-term fear is more than 2 standard deviations above its 1-year average relative to medium-term fear — a yellow alert banner appears on the indicator page.

This condition does **not** change the composite or the signal. It is a separate observation: when near-term panic is at an extreme, the probability of a short-term reversal increases, even if the composite is firmly in Risk Off territory. Traders who ignore this alert during extreme selloffs tend to miss the sharpest bounces.

Historical examples where the alert would have fired:
- March 2020 COVID crash bottom
- October 2022 CPI shock low
- April 9, 2025 Liberation Day reversal (VIX reached 52)

---

## Accuracy Tracker

### How It Works

Every daily refresh records an entry in Redis:
- The date
- The signal and composite score
- The three-bucket prediction (BULLISH / NEUTRAL / BEARISH)
- Today's SPY adjusted close

Ten trading days later, when the forward SPY close is available in the daily data pull, the entry is resolved: the 10-day return is computed, classified, and marked correct or incorrect.

### Why 10 Trading Days

The indicator is designed for the 2-8 week horizon. Ten trading days (two calendar weeks) sits in the middle of that range. It is long enough for the credit and macro flows the indicator measures to manifest in equity prices, and short enough that the signal is still clearly the dominant variable rather than new information arriving over a longer window.

Testing next-day accuracy would produce artificially low scores — on any given day, news events can overwhelm a multi-week positioning signal. Testing at 8 weeks introduces too much noise from intervening signals and regime changes.

### Why ±1.5% Neutral Band

Over 10 trading days, SPY's average absolute move is 2-3%. A ±0.1% neutral band (appropriate for next-day testing) would classify virtually every 10-day outcome as directional, leaving the NEUTRAL bucket nearly empty and making neutral predictions impossible to score as correct.

A ±1.5% band captures genuinely flat 10-day periods — roughly 15-20% of outcomes — while treating everything else as directional. This is consistent with what "neutral" means for a 2-week investment decision: if SPY moves less than 1.5% in either direction over two weeks, the market is genuinely going nowhere.

### Prediction Rules

| Signal | Prediction | Correct If |
|--------|------------|------------|
| Risk On / Lean Risk On | BULLISH | SPY +10d return > +1.5% |
| Neutral | NEUTRAL | SPY +10d return within ±1.5% |
| Lean Risk Off / Risk Off | BEARISH | SPY +10d return < -1.5% |

### Stats Displayed

- **Overall %** — correct predictions divided by all resolved signals
- **Directional %** — correct predictions among BULLISH and BEARISH calls only (excludes NEUTRAL, which is the hardest to score and least actionable for positioning)
- **Bullish calls** — accuracy of all Risk On / Lean Risk On signals specifically
- **Bearish calls** — accuracy of all Risk Off / Lean Risk Off signals specifically
- **History table** — last 20 entries showing signal date, forward date, 10-day SPY return, outcome, and correct/incorrect mark. Pending entries (awaiting the 10th forward trading day) show at reduced opacity with a "+10d pending" note

### What Good Accuracy Looks Like

A random three-bucket prediction has 33% baseline accuracy. In practice, SPY goes up more than 1.5% over 10 days in roughly 45% of periods, goes down more than 1.5% in roughly 30%, and stays flat in roughly 25%. A naive "always bullish" strategy gets ~45% overall. A meaningful indicator should beat this naive baseline — particularly on the BEARISH calls, which are harder and more valuable to get right.

An indicator scoring above 55% overall and 60%+ on directional calls is demonstrating genuine signal. Accuracy will vary by market regime: highest during sustained trends (2023 bull run), lowest during sudden shock-and-reversal events where the signal shifts faster than the 10-day window can score it.

### Building Up History

The accuracy card is hidden until at least one signal has been resolved (which takes 10 trading days after first deployment). History builds entry by entry. After 252 resolved signals (approximately one trading year), the rolling window is fully populated and the stats represent a genuine 12-month track record.

---

## Technical Architecture

### Data Pipeline

```
Daily /refresh (triggered by cron-job.org at 6pm CT)
    |
    v
Tiingo API: fetch 340 days of adjusted closes for 12 tickers
    |
    +-- Compute 252-day z-scores for each component
    +-- Weight and sum into composite
    +-- Classify signal
    +-- Check VIX reversal alert
    |
    v
_update_history()
    +-- Load rolling history from Redis
    +-- Resolve all pending entries with 10-day forward data now available
    +-- Append today's new pending entry
    +-- Trim to 262 entries (252 completed + up to 10 pending)
    +-- Compute accuracy stats
    +-- Save history to Redis
    |
    v
Save result + accuracy stats to Redis (25-hour TTL)
```

### Redis Storage

| Key | Contents | TTL |
|-----|----------|-----|
| `risk_indicator_v2` | Latest composite, signal, components, accuracy stats | 25 hours |
| `risk_indicator_history_v2` | Rolling 262-entry signal log | ~55 hours |

### Configuration Constants

These are at the top of `risk_indicator.py` and can be adjusted without touching any other code:

```python
FORWARD_DAYS = 10    # trading days forward to measure SPY return
NEUTRAL_BAND = 1.5   # +/- % for neutral classification
MAX_HISTORY  = 262   # 252 completed + up to 10 pending
```

### API Endpoint

`GET /api/risk-indicator`

Returns JSON with the full indicator result including accuracy stats. The response includes `Access-Control-Allow-Origin: *` so external dashboards (including the KCM Mutual Fund dashboard) can fetch it cross-origin.

Returns HTTP 503 with an error message if the indicator has not yet been computed (e.g., first deploy before the initial `/refresh`).

---

## Performance in Stress Periods

### April 2025 Tariff Tantrum

The composite began drifting negative in mid-March as HYG/IEI spreads widened and CPER/GLD fell on manufacturing demand concerns. By Liberation Day (April 2) the composite was firmly in Risk Off. The VIX reversal alert fired on April 8-9 when VIX spiked to 52, signaling the extreme panic condition. The market reversed 9.5% on April 9 when the 90-day tariff pause was announced.

The indicator's credit component (HYG/IEI) led the equity components by approximately 2-3 weeks in this event — consistent with its theoretical grounding.

### March-April 2026 Iran War

The composite moved into Lean Risk Off on the onset of military operations. However, the USD/JPY signal (had it been included as the sole currency component) would have been muted — the dollar strengthened alongside the yen as both served as safe havens simultaneously. The FXF (Swiss franc) component provided the cleaner risk-off signal that USD/JPY missed, validating the decision to use a two-currency basket.

The VIX during the Iran conflict peaked around 23 — significantly lower than the 52 reached during the tariff tantrum — consistent with markets pricing in a short, contained military operation rather than an existential economic shock.

---

## Limitations

**Designed for 2-8 weeks, not daily trading.** The indicator smooths over daily noise by design. Using it for day-trading decisions will produce disappointing results.

**Neutral calls are genuinely hard to score.** Over any 10-trading-day window, the market tends to trend. Sustained flat periods are relatively rare, which means NEUTRAL predictions will have lower accuracy than BULLISH or BEARISH calls by nature of market structure — not because the indicator is wrong.

**Regime dependency.** No indicator works equally well in all regimes. The composite will tend to be most accurate in sustained trending markets and least accurate in sudden shock-and-reversal events where the signal shifts faster than the 10-day window can capture.

**CPER availability.** The US Copper Index Fund (CPER) may not be available on all Tiingo subscription tiers. If CPER returns null, the composite automatically renormalizes across the remaining five components. DBB (DB Base Metals ETF) is an acceptable substitute — change the ticker in `risk_indicator.py` under the `copper_gold` component definition.

**History starts from first deployment.** The accuracy tracker builds from zero on first install. There is no backfilled historical accuracy data. A full 252-signal rolling window takes approximately one trading year to accumulate.

---

## Files

| File | Purpose |
|------|---------|
| `risk_indicator.py` | All computation: fetch, z-scores, composite, accuracy tracker, Redis I/O |
| `templates/risk_indicator.html` | Full indicator page: gauge, component breakdown, accuracy card |
| `app.py` | Calls `refresh_risk_data()` at end of daily ETF refresh; serves `/risk-indicator` and `/api/risk-indicator` routes |
