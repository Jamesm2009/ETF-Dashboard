KCM ETF Performance Dashboard
A self-hosted, daily-refreshing ETF and mutual fund performance dashboard built with Flask, Tiingo market data, Upstash Redis, and deployed on Render. Includes a composite Risk On/Off indicator, market breadth meters, and a signal accuracy tracker.
---
Live URLs
App	URL
ETF Dashboard	https://etf.market-dashboards.com/
Risk Indicator	https://etf.market-dashboards.com/risk-indicator
Status	https://etf.market-dashboards.com/status
Force Refresh	https://etf.market-dashboards.com/refresh
---
Features
ETF Performance Table
Ranks all ETFs in `funds.json` by Relative Strength (RS) score.
RS Score formula: `(1D x 0.10) + (1W x 0.20) + (1M x 0.30) + (3M x 0.40)`
Each row shows:
Name, sparkline (8-month price chart with 63-day SMA overlay)
Color-coded category tag (US Equity, International, Bond, Commodity)
Performance: 1D, 1W, 1M, 3M, 6M, YTD, 1Y
3-year price range bar with current price position
Expense ratio, RS score, 1-year Z-score, Overbought/Oversold flag
21-day and 63-day SMA signal dots (green = above, red = below)
RS rank, ticker link to Yahoo Finance
Market Breadth Meters
Displayed in the dashboard header. Shows what percentage of ETFs are trading above or below their moving averages:
1 Month — above/below 21-day SMA (using `trade_flag` from each fund)
3 Month — above/below 63-day SMA (using `trend_flag` from each fund)
Counts and percentages update automatically when funds are added or removed from `funds.json`. ETFs with insufficient history (grey flag) are excluded from both sides, so percentages always sum to 100%.
Risk On/Off Indicator
A six-component composite indicator designed for the 2-8 week investment horizon. Displays as a color-banded gauge with needle on the `/risk-indicator` page, and as a compact badge in the dashboard header.
Components and weights:
Component	Tickers	Weight	What It Measures
S&P Long/Short	SPY / SH	20%	Broad equity sentiment, no leveraged-ETF drift
Nasdaq Long/Short	TQQQ / SQQQ	15%	Tech/growth appetite, tends to lead market
Credit vs Treasury	HYG / IEI	25%	Institutional credit stress, leads equity by 3-10 days
Copper vs Gold	CPER / GLD	20%	Global growth demand vs safe-haven fear
Safe-Haven FX (Yen)	FXY	7.5%	Yen strengthens on risk-off flows
Safe-Haven FX (Franc)	FXF	7.5%	Franc rises on geopolitical fear
VIX Term Structure	VIXY / VIXM	5%	Near-term vs medium-term fear, reversal signal
All z-scores computed over a trailing 252-day (1-year) window.
Signal thresholds:
Composite Z-Score	Signal
> +1.00	Risk On
+0.25 to +1.00	Lean Risk On
-0.25 to +0.25	Neutral
-1.00 to -0.25	Lean Risk Off
< -1.00	Risk Off
VIX Reversal Alert: When the VIXY/VIXM term structure z-score drops below -2.0 (extreme near-term panic relative to medium-term), an alert is shown. This condition historically precedes short-term market bottoms.
Why copper/gold and credit beat equity ratios alone:
Credit spreads (HYG/IEI) lead equity moves by 3-10 days because institutional investors rebalance debt before equity
Copper/gold is regime-independent — unlike USD/JPY, it signals the same way in both trade wars and geopolitical crises
The Swiss franc (FXF) fills the gap when USD/JPY is muted (e.g., geopolitical events where the dollar also strengthens as a safe haven)
Signal Accuracy Tracker
Displayed below the component breakdown on the Risk Indicator page. Tracks how often the indicator's daily signal correctly predicted the next day's SPY direction over a rolling 252-day window.
Prediction rules:
Risk On / Lean Risk On → Bullish → correct if SPY next day > +0.1%
Neutral → Neutral → correct if SPY next day within ±0.1%
Lean Risk Off / Risk Off → Bearish → correct if SPY next day < -0.1%
Stats displayed:
Overall accuracy % (all signals)
Directional accuracy % (bullish and bearish calls only, excluding neutral)
Bullish call accuracy separately
Bearish call accuracy separately
Rolling accuracy bar
Last 20 days history table with signal, prediction, SPY % change, actual outcome, and correct/incorrect
History builds day by day. After the first refresh there are 0 completed entries; after the second there is 1; after 252 trading days there is a full year. The accuracy card is hidden until at least 1 entry is completed.
---
Architecture
```
GitHub repo
    |
    v
Render (free tier web service)
    |-- Flask app (app.py)
    |-- Daily data refresh via cron-job.org -> /refresh
    |-- Upstash Redis (persistent cache, survives Render spindowns)
    |-- Tiingo API (market data)
```
Data flow
Cron job hits `/refresh` once daily after market close (6:00pm CT)
`run_update()` loops through every ticker in `funds.json`, fetching 3 years of history from Tiingo
Each ticker is saved to Redis as it completes (so partial progress survives if Render spins down)
After all ETFs load, the Risk On/Off indicator fetches its 12 tickers and computes the composite
The accuracy tracker resolves yesterday's pending signal using today's SPY close, then records today's signal as pending
All results cached in Redis with a 25-hour TTL
All page loads serve instantly from Redis cache — no Tiingo calls on page load
Redis keys
Key	Contents	TTL
`etf_dashboard_cache`	Full ETF data, ranked list, last_updated	25 hrs
`etf_dashboard_progress`	Set of completed symbols (for resuming)	25 hrs
`risk_indicator_v2`	Latest risk indicator result + accuracy stats	25 hrs
`risk_indicator_history_v1`	Rolling 253-entry signal history log	~55 hrs
Rate limit handling
Tiingo's free tier allows 50 requests/hour. The ETF refresh sleeps 3 seconds between tickers. If a 429 is received, the app calculates time to the next hour reset, sleeps, then resumes. Progress is saved to Redis before sleeping so no work is lost.
---
File Structure
```
/
|-- app.py                  Main Flask app, routes, ETF data pipeline
|-- risk_indicator.py       Risk On/Off composite indicator + accuracy tracker
|-- funds.json              List of ETFs to track (add/remove here)
|-- requirements.txt        Python dependencies
|-- templates/
|   |-- index.html          ETF dashboard main page
|   |-- risk_indicator.html Risk On/Off indicator page
```
---
Adding or Removing ETFs
Edit `funds.json`. Each entry:
```json
{
  "symbol":    "SPY",
  "name":      "SPDR S&P 500 ETF Trust",
  "category":  "Equity US | Large Cap Blend",
  "type":      "etf",
  "exp_ratio": 0.0945
}
```
`ttm_yield` is optional. After saving, hit `/refresh` to reload. The breadth meters update automatically to reflect the new universe.
Category tag colors in the dashboard are assigned automatically:
Blue — US equity, sector, thematic, factor, momentum
Teal — International, emerging markets, global
Amber — Bonds, fixed income, treasury, credit
Yellow — Commodities, gold, oil, metals
---
Environment Variables
Set these in the Render dashboard under Environment:
Variable	Description
`TIINGO_TOKEN`	Tiingo API key (free tier works)
`UPSTASH_REDIS_REST_URL`	Upstash Redis REST endpoint URL
`UPSTASH_REDIS_REST_TOKEN`	Upstash Redis REST token
---
Routes
Route	Description
`/`	Main ETF dashboard (served from cache)
`/risk-indicator`	Full Risk On/Off indicator page
`/api/risk-indicator`	JSON API for risk indicator (CORS-enabled)
`/api/data`	JSON API for full ETF ranked list
`/refresh`	Trigger a full data refresh (clears cache, restarts pipeline)
`/status`	JSON status: phase, funds loaded, progress message, last_updated
---
Cron Jobs (cron-job.org)
Two jobs keep the dashboard alive and current:
Job	URL	Schedule	Purpose
Daily refresh	`/refresh`	5:00pm CT, Mon-Fri	Fetch new market data after close
---
MF Dashboard Integration
The KCM Mutual Fund dashboard displays the Risk On/Off badge in its header via a JavaScript fetch from the ETF dashboard's public API. No changes to the MF app.py are required — the badge is entirely client-side.
The ETF dashboard's `/api/risk-indicator` route sends `Access-Control-Allow-Origin: *` so the browser allows the cross-origin request.
If the ETF dashboard is spun down (Render free tier), the MF badge shows a neutral gray placeholder rather than erroring.
---
Metrics Explained
Metric	Calculation	Interpretation
RS Score	(1D x 0.10) + (1W x 0.20) + (1M x 0.30) + (3M x 0.40)	Higher = stronger recent momentum. Rank 1 = strongest.
1-Year Z-Score	(current - 1yr mean) / 1yr std dev	> 2.10 = Overbought, < -2.05 = Oversold
21d SMA dot	Current price vs 21-day simple moving average	Green = above (short-term bullish), Red = below
63d SMA dot	Current price vs 63-day simple moving average	Green = above (medium-term bullish), Red = below
3-Yr Range bar	Position of current price between 3-year low and high	100% = at all-time 3-year high
Risk composite	Weighted average of six 252-day z-scores	Positive = risk-on regime, negative = risk-off
---
Dependencies
```
flask
requests
pandas
numpy
```
No database required. All persistence is handled by Upstash Redis via REST API (no redis-py library needed).
---
Deployment (Render)
Connect GitHub repo to Render as a Web Service
Set runtime to Python 3
Build command: `pip install -r requirements.txt`
Start command: `gunicorn app:app`
Add environment variables (see above)
Deploy
On first deploy, visit `/refresh` to populate the cache. Subsequent refreshes run automatically via cron job.
