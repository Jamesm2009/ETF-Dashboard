"""
risk_indicator.py  -  Drop into the root of your ETF Dashboard project.

Composite Risk On/Off Indicator (six components, 252-day z-scores):
  1. SPY/SH ratio      (20%)  Broad equity sentiment, no leveraged-ETF drift
  2. TQQQ/SQQQ ratio   (15%)  Tech/growth appetite, tends to lead market
  3. HYG/IEI ratio     (25%)  Credit vs treasury, leads equity by 3-10 days
  4. CPER/GLD ratio    (20%)  Copper vs gold, growth vs fear
  5. FXY (yen ETF)     ( 7.5%) Safe-haven FX, inverted so +z = risk-on
  6. FXF (franc ETF)   ( 7.5%) Safe-haven FX, inverted so +z = risk-on
  7. VIXY/VIXM ratio   ( 5%)  VIX term structure, reversal alert when extreme

Accuracy tracker (10-day forward window):
  Each daily run records today's signal + today's SPY close.
  Entries are resolved when SPY data for 10 trading days forward is available.
  Builds a rolling 252-entry log in Redis. Stats accumulate day by day.

  Prediction mapping:
    Risk On / Lean Risk On  -> BULLISH -> correct if SPY +10d return > +1.5%
    Neutral                 -> NEUTRAL -> correct if SPY +10d return within +/-1.5%
    Lean Risk Off / Risk Off-> BEARISH -> correct if SPY +10d return < -1.5%

  Why 1.5% neutral band:
    Over 10 trading days SPY's average absolute move is 2-3%.
    A +/-0.1% band (suitable for next-day) would classify almost everything
    as directional over 10 days, leaving the neutral bucket nearly empty.
    +/-1.5% captures genuinely flat 10-day periods (~15-20% of outcomes)
    while treating meaningful moves as directional.

USAGE in app.py:

  Daily batch (at end of run_update):
    from risk_indicator import refresh_risk_data
    refresh_risk_data(redis_set_fn=redis_set, redis_get_fn=redis_get)

  Read from cache (in routes):
    from risk_indicator import get_cached_risk
    data = get_cached_risk(redis_get_fn=redis_get)
    # data["accuracy"] contains full stats and recent history
"""

import os
import requests
import numpy as np
from datetime import datetime, date, timedelta

TIINGO_TOKEN = os.environ.get("TIINGO_TOKEN", "")
TIINGO_BASE  = "https://api.tiingo.com/tiingo/daily"
REDIS_KEY    = "risk_indicator_v2"
HISTORY_KEY  = "risk_indicator_history_v2"   # v2: 10-day window

# ---------------------------------------------------------------------------
# Accuracy tracker settings  (change these to experiment)
# ---------------------------------------------------------------------------
FORWARD_DAYS = 10    # trading days forward to measure SPY return
NEUTRAL_BAND = 1.5   # +/- % threshold; inside = NEUTRAL, outside = directional
MAX_HISTORY  = 262   # 252 completed + up to 10 pending at any time

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
# Tiingo fetch
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


def _signal_to_bucket(signal):
    """Collapse five signals into three directional predictions."""
    if signal in ("Risk On", "Lean Risk On"):
        return "BULLISH"
    elif signal in ("Risk Off", "Lean Risk Off"):
        return "BEARISH"
    else:
        return "NEUTRAL"


def _outcome(change_pct):
    """Classify a percentage change into BULLISH / NEUTRAL / BEARISH."""
    if change_pct > NEUTRAL_BAND:
        return "BULLISH"
    elif change_pct < -NEUTRAL_BAND:
        return "BEARISH"
    else:
        return "NEUTRAL"

# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------

def _compute():
    """
    Fetch all tickers, compute composite.
    Returns (result_dict, spy_prices) or (None, None).
    spy_prices is reused by the accuracy tracker to avoid a second API call.
    """
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
        return None, None

    total_w   = sum(c["weight"] for c in valid)
    composite = round(
        sum(c["weight"] * c["zscore"] for c in valid) / total_w,
        3
    )
    signal, color = _classify(composite)

    vix_comp = next((c for c in scored if c["key"] == "vix_term"), None)
    reversal_alert = None
    if (vix_comp and
            vix_comp.get("zscore") is not None and
            vix_comp["zscore"] < -2.0):
        reversal_alert = "Extreme near-term VIX spike - potential reversal may be near"

    result = {
        "composite":        composite,
        "signal":           signal,
        "signal_color":     color,
        "components":       scored,
        "reversal_alert":   reversal_alert,
        "components_used":  len(valid),
        "components_total": len(scored),
        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
    }

    return result, prices.get("SPY")

# ---------------------------------------------------------------------------
# Accuracy tracker
# ---------------------------------------------------------------------------

def _resolve_pending(history, spy_prices):
    """
    Scan all pending history entries and resolve any where the
    FORWARD_DAYS-th trading day is now available in spy_prices.

    This is called once per daily refresh. It handles:
      - Multiple entries becoming resolvable at once (e.g. after weekends)
      - Idempotency: already-resolved entries are skipped
      - Missing signal dates in SPY series (skipped gracefully)

    Returns the number of entries newly resolved.
    """
    if not spy_prices:
        return 0

    # Build a lookup: date_string -> index in sorted date list
    spy_dates  = sorted(spy_prices.keys())
    date_index = {d: i for i, d in enumerate(spy_dates)}
    resolved   = 0

    for entry in history:
        # Skip already-resolved entries
        if entry.get("correct") is not None:
            continue

        signal_date  = entry.get("date")
        signal_close = entry.get("spx_close")

        if not signal_date or signal_close is None:
            continue

        if signal_date not in date_index:
            # Signal date predates our SPY history window - cannot resolve
            continue

        forward_idx = date_index[signal_date] + FORWARD_DAYS
        if forward_idx >= len(spy_dates):
            # The 10th trading day forward has not yet occurred
            continue

        forward_date  = spy_dates[forward_idx]
        forward_close = spy_prices[forward_date]
        change_pct    = round(
            (forward_close - signal_close) / signal_close * 100, 3
        )
        actual = _outcome(change_pct)

        entry["spx_forward_date"]  = forward_date
        entry["spx_forward_close"] = round(forward_close, 2)
        entry["spx_change_pct"]    = change_pct
        entry["actual_outcome"]    = actual
        entry["correct"]           = (entry.get("predicted") == actual)
        resolved += 1

        print(
            f"  [risk] Resolved {signal_date} -> {forward_date} "
            f"({change_pct:+.2f}%): "
            f"predicted={entry['predicted']} actual={actual} "
            f"({'CORRECT' if entry['correct'] else 'WRONG'})"
        )

    return resolved


def _compute_accuracy_stats(completed):
    """Compute accuracy statistics from a list of completed history entries."""
    if not completed:
        return {
            "overall_pct":         None,
            "overall_correct":     0,
            "overall_total":       0,
            "directional_pct":     None,
            "directional_correct": 0,
            "directional_total":   0,
            "by_bucket":           {},
            "forward_days":        FORWARD_DAYS,
            "neutral_band":        NEUTRAL_BAND,
        }

    correct = sum(1 for e in completed if e.get("correct"))
    total   = len(completed)

    by_bucket = {}
    for bucket in ("BULLISH", "NEUTRAL", "BEARISH"):
        entries = [e for e in completed if e.get("predicted") == bucket]
        n = len(entries)
        c = sum(1 for e in entries if e.get("correct"))
        by_bucket[bucket] = {
            "correct": c,
            "total":   n,
            "pct":     round(c / n * 100, 1) if n > 0 else None,
        }

    # Directional accuracy excludes neutral predictions
    directional = [e for e in completed if e.get("predicted") != "NEUTRAL"]
    dir_n = len(directional)
    dir_c = sum(1 for e in directional if e.get("correct"))

    return {
        "overall_pct":         round(correct / total * 100, 1),
        "overall_correct":     correct,
        "overall_total":       total,
        "directional_pct":     round(dir_c / dir_n * 100, 1) if dir_n else None,
        "directional_correct": dir_c,
        "directional_total":   dir_n,
        "by_bucket":           by_bucket,
        "forward_days":        FORWARD_DAYS,
        "neutral_band":        NEUTRAL_BAND,
    }


def _update_history(redis_get_fn, redis_set_fn, signal, composite, spy_prices):
    """
    Update rolling accuracy history in Redis.

    Steps:
      1. Load existing history from Redis.
      2. Resolve ALL pending entries where 10 forward trading days of
         SPY data are now available.
      3. Append today's new pending entry (idempotent if already present).
      4. Trim to MAX_HISTORY entries.
      5. Compute and return accuracy stats.

    Returns accuracy stats dict, or None if spy_prices unavailable.
    """
    if not spy_prices:
        print("  [risk] No SPY prices - accuracy tracking skipped")
        return None

    spy_dates = sorted(spy_prices.keys())
    if not spy_dates:
        return None

    today_dt    = spy_dates[-1]
    today_close = round(spy_prices[today_dt], 2)

    # Load history
    history = redis_get_fn(HISTORY_KEY) or []

    # Resolve all pending entries that now have 10-day forward data
    n_resolved = _resolve_pending(history, spy_prices)
    if n_resolved:
        print(f"  [risk] Resolved {n_resolved} pending entries")

    # Append today's entry (skip if already recorded - idempotent)
    if not history or history[-1].get("date") != today_dt:
        history.append({
            "date":              today_dt,
            "signal":            signal,
            "composite":         composite,
            "predicted":         _signal_to_bucket(signal),
            "spx_close":         today_close,
            "spx_forward_date":  None,
            "spx_forward_close": None,
            "spx_change_pct":    None,   # filled in FORWARD_DAYS trading days later
            "actual_outcome":    None,
            "correct":           None,
        })
        print(f"  [risk] History: recorded {today_dt} signal={signal} "
              f"(resolves after {FORWARD_DAYS} trading days)")
    else:
        print(f"  [risk] History: {today_dt} already recorded")

    # Trim to keep only the most recent MAX_HISTORY entries
    history = history[-MAX_HISTORY:]

    # Build stats from completed (resolved) entries only
    completed = [e for e in history if e.get("correct") is not None]
    stats = _compute_accuracy_stats(completed)
    stats["days_tracked"]   = len(history)
    stats["days_completed"] = len(completed)
    stats["days_pending"]   = len(history) - len(completed)
    stats["days_target"]    = 252
    stats["recent"]         = list(reversed(history[-20:]))

    # Save
    redis_set_fn(HISTORY_KEY, history, ex_seconds=200000)
    acc = stats.get("overall_pct")
    print(
        f"  [risk] Accuracy ({FORWARD_DAYS}d): "
        f"{acc}% ({stats['overall_correct']}/{stats['overall_total']} resolved, "
        f"{stats['days_pending']} pending)"
    )
    return stats

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_risk_data(redis_set_fn, redis_get_fn=None):
    """
    Fetch fresh market data, compute composite, update accuracy history,
    store everything in Redis. Called once daily at end of run_update().

    Args:
        redis_set_fn:  redis_set(key, value, ex_seconds) from app.py
        redis_get_fn:  redis_get(key) from app.py  (needed for history)
    Returns:
        result dict (includes accuracy key), or None if compute failed
    """
    result, spy_prices = _compute()
    if result is None:
        print("  [risk] Compute failed - nothing saved to Redis")
        return None

    accuracy = None
    if redis_get_fn is not None and spy_prices is not None:
        try:
            accuracy = _update_history(
                redis_get_fn=redis_get_fn,
                redis_set_fn=redis_set_fn,
                signal=result["signal"],
                composite=result["composite"],
                spy_prices=spy_prices,
            )
        except Exception as e:
            print(f"  [risk] Accuracy update error: {e}")

    result["accuracy"] = accuracy
    redis_set_fn(REDIS_KEY, result, ex_seconds=90000)
    print(f"  [risk] Redis saved: {result['signal']} ({result['composite']:+.2f})")
    return result


def get_cached_risk(redis_get_fn):
    """
    Return the most recently computed risk indicator from Redis.
    Includes result['accuracy'] with full stats and recent history.
    """
    return redis_get_fn(REDIS_KEY)
