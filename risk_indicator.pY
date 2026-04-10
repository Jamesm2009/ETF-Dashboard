“””
risk_indicator.py  —  Drop this into the root of your ETF Dashboard project.

Composite Risk On/Off Indicator using six components:

1. SPY/SH ratio z-score         (20%)  Broad equity sentiment
1. TQQQ/SQQQ ratio z-score      (15%)  Tech/growth sentiment (often leads market)
1. HYG/IEI ratio z-score        (25%)  Credit vs treasury — leads equity by 3-10 days
1. CPER/GLD ratio z-score       (20%)  Copper vs gold — growth vs fear
1. FXY + FXF z-scores inverted  (15%)  Safe-haven FX basket (yen + swiss franc)
1. VIXY/VIXM ratio z-score       (5%)  VIX term structure — reversal signal

All z-scores computed over trailing 252 trading days (~1 year).
Cached in Redis for 30 minutes to stay within Tiingo’s rate limits.

Signal thresholds:
composite >  1.00  →  Risk On
composite >  0.25  →  Lean Risk On
composite > -0.25  →  Neutral
composite > -1.00  →  Lean Risk Off
composite <= -1.00 →  Risk Off
“””

import os
import json
import requests
import numpy as np
from datetime import datetime, timedelta

TIINGO_KEY = os.environ.get(‘TIINGO_API_KEY’, ‘’)

# ─── Component definitions ────────────────────────────────────────────────────

# Ratio components: z-score of (a_price / b_price) over trailing 252 days

# invert=True means a HIGH ratio = risk-off, so we flip the sign to match the scale.

RATIO_COMPONENTS = [
{
‘key’:         ‘spy_sh’,
‘label’:       ‘S&P Long/Short (SPY/SH)’,
‘description’: ‘Broad equity sentiment — how elevated the bull/bear ratio is vs. its 1-yr average’,
‘a’: ‘SPY’,  ‘b’: ‘SH’,
‘weight’:  0.20,
‘invert’:  False,
},
{
‘key’:         ‘tqqq_sqqq’,
‘label’:       ‘Nasdaq Long/Short (TQQQ/SQQQ)’,
‘description’: ‘Tech/growth appetite — amplified signal, tends to lead the broader market’,
‘a’: ‘TQQQ’, ‘b’: ‘SQQQ’,
‘weight’:  0.15,
‘invert’:  False,
},
{
‘key’:         ‘hyg_iei’,
‘label’:       ‘Credit vs Treasury (HYG/IEI)’,
‘description’: ‘Credit spreads — institutional money moves here 3-10 days before equities’,
‘a’: ‘HYG’,  ‘b’: ‘IEI’,
‘weight’:  0.25,
‘invert’:  False,
},
{
‘key’:         ‘copper_gold’,
‘label’:       ‘Copper vs Gold (CPER/GLD)’,
‘description’: ‘Growth vs fear ratio — copper tracks global demand, gold tracks safe-haven bids’,
‘a’: ‘CPER’, ‘b’: ‘GLD’,
‘weight’:  0.20,
‘invert’:  False,
},
{
‘key’:         ‘vix_term’,
‘label’:       ‘VIX Term Structure (VIXY/VIXM)’,
‘description’: ‘Near-term vs medium-term fear — extreme spikes often signal a reversal is near’,
‘a’: ‘VIXY’, ‘b’: ‘VIXM’,
‘weight’:  0.05,
‘invert’:  True,   # High VIXY/VIXM = panic spike = risk-off (flip sign)
},
]

# Single-ticker FX components — yen and swiss franc ETFs.

# Both RISE on risk-off (safe-haven inflows), so we invert the z-score.

FX_COMPONENTS = [
{
‘key’:         ‘fxy’,
‘label’:       ‘Japanese Yen ETF (FXY)’,
‘description’: ‘Yen strengthens on risk-off flows; inverted so +z = risk-on’,
‘ticker’:      ‘FXY’,
‘weight’:      0.075,
},
{
‘key’:         ‘fxf’,
‘label’:       ‘Swiss Franc ETF (FXF)’,
‘description’: ‘Franc strengthens on geopolitical risk-off; inverted so +z = risk-on’,
‘ticker’:      ‘FXF’,
‘weight’:      0.075,
},
]

# ─── Data helpers ─────────────────────────────────────────────────────────────

def _fetch(ticker, days=340):
“””
Fetch daily adjusted closing prices from Tiingo.
Returns {date_str: price} dict, or None on failure.
We fetch ~340 calendar days to ensure ~252 trading days of history.
“””
end   = datetime.today()
start = end - timedelta(days=days)
try:
resp = requests.get(
f’https://api.tiingo.com/tiingo/daily/{ticker}/prices’,
params={
‘startDate’: start.strftime(’%Y-%m-%d’),
‘endDate’:   end.strftime(’%Y-%m-%d’),
‘token’:     TIINGO_KEY,
},
timeout=15,
)
resp.raise_for_status()
rows = resp.json()
if not rows:
return None
return {row[‘date’][:10]: row[‘adjClose’] for row in rows if row.get(‘adjClose’)}
except Exception:
return None

def _ratio_series(pa, pb):
“””
Compute ratio pa/pb aligned on common dates.
Returns list of floats (chronological) or None if too few data points.
“””
common = sorted(set(pa) & set(pb))
if len(common) < 100:
return None
return [pa[d] / pb[d] for d in common]

def _zscore(series, window=252):
“””
Z-score of the most recent value versus the trailing window.
Returns float or None if data is insufficient / flat.
“””
arr = np.array(series[-window:] if len(series) >= window else series, dtype=float)
if len(arr) < 60:
return None
std = arr.std()
if std == 0:
return 0.0
return float((arr[-1] - arr.mean()) / std)

# ─── Main function ────────────────────────────────────────────────────────────

def get_risk_indicator(redis_client=None):
“””
Compute (and optionally cache) the composite Risk On/Off indicator.

```
Args:
    redis_client:  Your existing Upstash Redis client (optional).
                   Results are cached for 30 minutes to minimise Tiingo API calls.

Returns:
    dict with keys:
      composite        — float, weighted average z-score
      signal           — str, e.g. 'Risk On'
      signal_color     — hex color string
      components       — list of component detail dicts
      reversal_alert   — str or None
      components_used  — int
      components_total — int
      timestamp        — str
"""
CACHE_KEY = 'risk_indicator_v2'

# ── Try cache ────────────────────────────────────────────────────────────
if redis_client:
    try:
        cached = redis_client.get(CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

# ── Fetch all tickers in one pass ────────────────────────────────────────
all_tickers = set()
for c in RATIO_COMPONENTS:
    all_tickers |= {c['a'], c['b']}
for c in FX_COMPONENTS:
    all_tickers.add(c['ticker'])

prices = {t: _fetch(t) for t in all_tickers}

# ── Score each component ─────────────────────────────────────────────────
scored = []

for comp in RATIO_COMPONENTS:
    pa = prices.get(comp['a'])
    pb = prices.get(comp['b'])
    entry = {k: comp[k] for k in ('key', 'label', 'description', 'weight')}

    if pa is None or pb is None:
        entry.update(zscore=None, status='unavailable')
        scored.append(entry)
        continue

    series = _ratio_series(pa, pb)
    if not series:
        entry.update(zscore=None, status='insufficient_data')
        scored.append(entry)
        continue

    z = _zscore(series)
    if z is None:
        entry.update(zscore=None, status='error')
        scored.append(entry)
        continue

    z = -z if comp['invert'] else z
    entry.update(zscore=round(z, 3), status='ok')
    scored.append(entry)

for comp in FX_COMPONENTS:
    px = prices.get(comp['ticker'])
    entry = {k: comp[k] for k in ('key', 'label', 'description', 'weight')}

    if px is None:
        entry.update(zscore=None, status='unavailable')
        scored.append(entry)
        continue

    series = [px[d] for d in sorted(px)]
    z = _zscore(series)
    if z is None:
        entry.update(zscore=None, status='error')
        scored.append(entry)
        continue

    # Invert: rising FXY/FXF = safe-haven demand = risk-off
    entry.update(zscore=round(-z, 3), status='ok')
    scored.append(entry)

# ── Weighted composite ───────────────────────────────────────────────────
valid = [c for c in scored if c.get('zscore') is not None]
if not valid:
    return {
        'error':     'Could not fetch data from Tiingo — check API key and ticker availability',
        'timestamp': datetime.now().isoformat(),
    }

total_w   = sum(c['weight'] for c in valid)
composite = sum(c['weight'] * c['zscore'] for c in valid) / total_w
composite = round(composite, 3)

# ── Signal ───────────────────────────────────────────────────────────────
if   composite >  1.00: signal, color = 'Risk On',       '#16a34a'
elif composite >  0.25: signal, color = 'Lean Risk On',  '#4ade80'
elif composite > -0.25: signal, color = 'Neutral',       '#f59e0b'
elif composite > -1.00: signal, color = 'Lean Risk Off', '#f87171'
else:                   signal, color = 'Risk Off',       '#dc2626'

# ── VIX reversal alert ───────────────────────────────────────────────────
# When near-term VIX is extremely elevated vs medium-term, a bottom is often near.
# After inversion, vix_term zscore will be very negative when VIXY >> VIXM.
vix = next((c for c in scored if c['key'] == 'vix_term'), None)
reversal_alert = None
if vix and vix.get('zscore') is not None and vix['zscore'] < -2.0:
    reversal_alert = 'Extreme near-term VIX spike — potential reversal may be near'

result = {
    'composite':        composite,
    'signal':           signal,
    'signal_color':     color,
    'components':       scored,
    'reversal_alert':   reversal_alert,
    'components_used':  len(valid),
    'components_total': len(scored),
    'timestamp':        datetime.now().strftime('%Y-%m-%d %H:%M UTC'),
}

# ── Cache 30 minutes ─────────────────────────────────────────────────────
if redis_client:
    try:
        redis_client.setex(CACHE_KEY, 1800, json.dumps(result))
    except Exception:
        pass

return result
```
