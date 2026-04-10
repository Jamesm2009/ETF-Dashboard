"""
risk_indicator.py  -  Drop into the root of your ETF Dashboard project.

Composite Risk On/Off Indicator (six components, 252-day z-scores):
  1. SPY/SH ratio      (20%)  Broad equity sentiment, no leveraged-ETF drift
  2. TQQQ/SQQQ ratio   (15%)  Tech/growth appetite, tends to lead market
  3. HYG/IEI ratio     (25%)  Credit vs treasury - leads equity by 3-10 days
  4. CPER/GLD ratio    (20%)  Copper vs gold - growth vs fear
  5. FXY (yen ETF)     ( 7.5%) Safe-haven FX, inverted so +z = risk-on
  6. FXF (franc ETF)   ( 7.5%) Safe-haven FX, inverted so +z = risk-on
  7. VIXY/VIXM ratio   ( 5%)  VIX term structure, reversal alert when extreme

Signal thresholds:
  composite >  1.00  ->  Risk On
  composite >  0.25  ->  Lean Risk On
  composite > -0.25  ->  Neutral
  composite > -1.00  ->  Lean Risk Off
  composite <= -1.00 ->  Risk Off

USAGE in app.py:

  Daily batch (at end of run_update):
    from risk_indicator import refresh_risk_data
    refresh_risk_data(redis_set_fn=redis_set)

  Read from cache (in routes):
    from risk_indicator import get_cached_risk
    data = get_cached_risk(redis_get_fn=redis_get)
"""

import os
import requests
import numpy as np
from datetime import datetime, date, timedelta

TIINGO_TOKEN = os.environ.get("TIINGO_TOKEN", "")
TIINGO_BASE  = "https://api.tiingo.com/tiingo/daily"
REDIS_KEY    = "risk_indicator_v2"

# ---------------------------------------------------------------------------
# Component definitions
# ---------------------------------------------------------------------------

RATIO_COMPONENTS = [
    {
        "key":         "spy_sh",
        "label":       "S&P Long/Short (SPY/SH)",
        "description": "Broad equity sentiment vs 1-yr average",
        "a": "SPY",  "b": "SH",
        "weight": 0.20,
        "invert": False,
    },
    {
        "key":         "tqqq_sqqq",
        "label":       "Nasdaq Long/Short (TQQQ/SQQQ)",
        "description": "Tech/growth appetite, tends to lead the broader market",
        "a": "TQQQ", "b": "SQQQ",
        "weight": 0.15,
        "invert": False,
    },
    {
        "key":         "hyg_iei",
        "label":       "Credit vs Treasury (HYG/IEI)",
        "description": "Institutional credit stress, leads equity by 3-10 days",
        "a": "HYG",  "b": "IEI",
        "weight": 0.25,
        "invert": False,
    },
    {
        "key":         "copper_gold",
        "label":       "Copper vs Gold (CPER/GLD)",
        "description": "Global growth demand vs safe-haven fear",
        "a": "CPER", "b": "GLD",
        "weight": 0.20,
        "invert": False,
    },
    {
        "key":         "vix_term",
        "label":       "VIX Term Structure (VIXY/VIXM)",
        "description": "Near-term vs medium-term fear, extreme spikes signal reversals",
        "a": "VIXY", "b": "VIXM",
        "weight": 0.05,
        "invert": True,
    },
]

FX_COMPONENTS = [
    {
        "key":         "fxy",
        "label":       "Japanese Yen ETF (FXY)",
        "description": "Yen strengthens on risk-off flows, inverted so +z = risk-on",
        "ticker":      "FXY",
        "weight":      0.075,
    },
    {
        "key":         "fxf",
        "label":       "Swiss Franc ETF (FXF)",
        "description": "Franc rises on geopolitical fear, inverted so +z = risk-on",
        "ticker":      "FXF",
        "weight":      0.075,
    },
]

# ---------------------------------------------------------------------------
# Tiingo fetch  (mirrors pattern already used in app.py)
# ---------------------------------------------------------------------------

def _fetch_tiingo(ticker, days=340):
    """Fetch daily adjusted closes from Tiingo. Returns {date_str: price} or None."""
    if not TIINGO_TOKEN:
        print("  [risk] TIINGO_TOKEN not set")
        return None
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            f"{TIINGO_BASE}/{ticker}/prices",
            params={
                "startDate":    start,
                "token":        TIINGO_TOKEN,
                "resampleFreq": "daily",
            },
            timeout=20,
        )
        if resp.status_code == 404:
            print(f"  [risk] {ticker} not found on Tiingo (404)")
            return None
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        return {
            row["date"][:10]: row["adjClose"]
            for row in rows
            if row.get("adjClose") is not None
        }
    except Exception as e:
        print(f"  [risk] fetch error {ticker}: {e}")
        return None

# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

def _ratio_series(pa, pb):
    """Aligned ratio series, chronological list of floats."""
    common = sorted(set(pa) & set(pb))
    if len(common) < 100:
        return None
    return [pa[d] / pb[d] for d in common]


def _zscore(series, window=252):
    """Z-score of the most recent value vs the trailing window."""
    arr = np.array(
        series[-window:] if len(series) >= window else series,
        dtype=float
    )
    if len(arr) < 60:
        return None
    std = float(arr.std())
    if std == 0:
        return 0.0
    return float((arr[-1] - arr.mean()) / std)

# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------

def _classify(composite):
    if   composite >  1.00: return "Risk On",       "#16a34a"
    elif composite >  0.25: return "Lean Risk On",  "#4ade80"
    elif composite > -0.25: return "Neutral",        "#f59e0b"
    elif composite > -1.00: return "Lean Risk Off", "#f87171"
    else:                   return "Risk Off",       "#dc2626"

# ---------------------------------------------------------------------------
# Core compute  (no Redis, pure calculation)
# ---------------------------------------------------------------------------

def _compute():
    """Fetch all tickers, compute composite. Returns result dict or None."""
    print("  [risk] Starting fetch...")

    all_tickers = set()
    for c in RATIO_COMPONENTS:
        all_tickers |= {c["a"], c["b"]}
    for c in FX_COMPONENTS:
        all_tickers.add(c["ticker"])

    prices = {}
    for ticker in sorted(all_tickers):
        prices[ticker] = _fetch_tiingo(ticker)
        status = "ok" if prices[ticker] else "FAILED"
        print(f"  [risk]   {ticker}: {status}")

    scored = []

    for comp in RATIO_COMPONENTS:
        pa = prices.get(comp["a"])
        pb = prices.get(comp["b"])
        entry = {k: comp[k] for k in ("key", "label", "description", "weight")}

        if pa is None or pb is None:
            entry.update(zscore=None, status="unavailable")
            scored.append(entry)
            continue

        series = _ratio_series(pa, pb)
        if series is None:
            entry.update(zscore=None, status="insufficient_data")
            scored.append(entry)
            continue

        z = _zscore(series)
        if z is None:
            entry.update(zscore=None, status="error")
            scored.append(entry)
            continue

        z = -z if comp["invert"] else z
        entry.update(zscore=round(z, 3), status="ok")
        scored.append(entry)

    for comp in FX_COMPONENTS:
        px = prices.get(comp["ticker"])
        entry = {k: comp[k] for k in ("key", "label", "description", "weight")}

        if px is None:
            entry.update(zscore=None, status="unavailable")
            scored.append(entry)
            continue

        series = [px[d] for d in sorted(px)]
        z = _zscore(series)
        if z is None:
            entry.update(zscore=None, status="error")
            scored.append(entry)
            continue

        # Invert: rising yen/franc = safe-haven demand = risk-off
        entry.update(zscore=round(-z, 3), status="ok")
        scored.append(entry)

    valid = [c for c in scored if c.get("zscore") is not None]
    if not valid:
        print("  [risk] No valid components - skipping")
        return None

    total_w   = sum(c["weight"] for c in valid)
    composite = round(
        sum(c["weight"] * c["zscore"] for c in valid) / total_w,
        3
    )
    signal, color = _classify(composite)

    # VIX reversal alert: post-inversion the vix_term score is very negative
    # when near-term panic massively exceeds medium-term - often signals a bottom
    vix_comp = next((c for c in scored if c["key"] == "vix_term"), None)
    reversal_alert = None
    if (vix_comp and
            vix_comp.get("zscore") is not None and
            vix_comp["zscore"] < -2.0):
        reversal_alert = "Extreme near-term VIX spike - potential reversal may be near"

    return {
        "composite":        composite,
        "signal":           signal,
        "signal_color":     color,
        "components":       scored,
        "reversal_alert":   reversal_alert,
        "components_used":  len(valid),
        "components_total": len(scored),
        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
    }

# ---------------------------------------------------------------------------
# Public API  (called from app.py)
# ---------------------------------------------------------------------------

def refresh_risk_data(redis_set_fn):
    """
    Fetch fresh market data, compute composite, store result in Redis.
    Called once daily at the end of run_update() in app.py.

    Args:
        redis_set_fn: the redis_set(key, value, ex_seconds) function from app.py
    Returns:
        result dict, or None if fetch failed
    """
    result = _compute()
    if result is None:
        print("  [risk] Compute failed - nothing saved to Redis")
        return None
    redis_set_fn(REDIS_KEY, result, ex_seconds=90000)
    print(f"  [risk] Redis saved: {result['signal']} ({result['composite']:+.2f})")
    return result


def get_cached_risk(redis_get_fn):
    """
    Return the most recently computed risk indicator from Redis.
    Called from routes in app.py.

    Args:
        redis_get_fn: the redis_get(key) function from app.py
    Returns:
        dict or None
    """
    return redis_get_fn(REDIS_KEY)
