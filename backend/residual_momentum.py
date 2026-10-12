"""
Residual momentum (Blitz, Huij & Martens, 2011): rank stocks by the part of
their return that ISN'T explained by common risk-factor exposure, rather
than by raw total return. This is a distinct, complementary signal to the
main scorer's Momentum bucket -- not a replacement -- surfaced separately
until there's been a chance to see how it behaves on real data.

Methodology (see research/garp-momentum-literature-review.html for the
citation and reasoning):
  1. For each stock, take its trailing 36 MONTHLY returns.
  2. Regress (stock return - risk-free rate) on the Fama-French 3 factors
     (Mkt-RF, SMB, HML) via OLS across all 36 months -- this estimates how
     much of the stock's return is just market/size/value beta.
  3. Take the residuals (actual - fitted) from the most recent 12 of those
     36 months, EXCLUDING the single most recent month (the standard
     momentum skip-month, avoiding short-term reversal contamination).
  4. Score = mean(those 12 residuals) / stdev(those 12 residuals) -- a
     t-stat-like measure that rewards *consistent* outperformance of a
     stock's own factor-implied return, not one big month.

Data sources:
  - Fama-French factors: Kenneth French's Data Library (free, public,
    updated monthly with a ~1-2 month lag -- so this signal is necessarily
    that far behind "today", a disclosed limitation of using free data).
  - Stock returns: Schwab daily price history, resampled to month-end
    closes. This is a PRICE return, not a total return -- dividends aren't
    added back in, which will understate returns for high-yield names.
    A disclosed simplification, not an attempt to exactly reproduce the
    original paper's data construction.

Usage:
  python backend/residual_momentum.py             # full S&P 500
  python backend/residual_momentum.py --limit 20  # quick test
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scorer  # noqa: E402
import schwab_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "data" / "residual_momentum.json"
FF3_CACHE_PATH = ROOT / "data" / "ff3_factors.json"
FF3_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"

ESTIMATION_MONTHS = 36
FORMATION_MONTHS = 12


def normalize_for_schwab_history(ticker: str) -> str:
    """Schwab's price-history endpoint wants share classes slash-separated
    (BRK/B), unlike Finviz's dash (BRK-B) or the standard dot (BRK.B)."""
    return ticker.replace(".", "/")


def fetch_ff3_factors(max_age_days: int = 25) -> dict[str, dict]:
    if FF3_CACHE_PATH.exists():
        age_days = (datetime.now(timezone.utc).timestamp() - FF3_CACHE_PATH.stat().st_mtime) / 86400
        if age_days < max_age_days:
            return json.loads(FF3_CACHE_PATH.read_text())

    resp = urllib.request.urlopen(FF3_URL, timeout=30)
    zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    text = zf.read(zf.namelist()[0]).decode("utf-8", errors="ignore")

    factors: dict[str, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d{6}),\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)$", line)
        if m:
            ym, mkt_rf, smb, hml, rf = m.groups()
            factors[ym] = {
                "mkt_rf": float(mkt_rf) / 100,
                "smb": float(smb) / 100,
                "hml": float(hml) / 100,
                "rf": float(rf) / 100,
            }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    FF3_CACHE_PATH.write_text(json.dumps(factors))
    return factors


def monthly_returns_from_candles(candles: list[dict]) -> dict[str, float]:
    month_close: dict[str, float] = {}
    for c in candles:
        dt = datetime.fromtimestamp(c["datetime"] / 1000, tz=timezone.utc)
        ym = f"{dt.year:04d}{dt.month:02d}"
        month_close[ym] = c["close"]  # candles are chronological; last write per month = month-end close

    months = sorted(month_close.keys())
    returns = {}
    for prev_ym, cur_ym in zip(months, months[1:]):
        prev_close, cur_close = month_close[prev_ym], month_close[cur_ym]
        if prev_close:
            returns[cur_ym] = (cur_close / prev_close) - 1
    return returns


def compute_residual_momentum(stock_returns: dict[str, float], ff3: dict[str, dict]) -> Optional[dict]:
    common = sorted(set(stock_returns) & set(ff3))
    if len(common) < ESTIMATION_MONTHS:
        return None

    window = common[-ESTIMATION_MONTHS:]
    X = np.array([[1.0, ff3[ym]["mkt_rf"], ff3[ym]["smb"], ff3[ym]["hml"]] for ym in window])
    y = np.array([stock_returns[ym] - ff3[ym]["rf"] for ym in window])

    coeffs, *_ = np.linalg.lstsq(X, y, rcond=None)
    alpha, beta_mkt, beta_smb, beta_hml = coeffs
    residuals = y - X @ coeffs

    formation = residuals[-(FORMATION_MONTHS + 1):-1]  # most recent 12, skipping the latest month
    if len(formation) < FORMATION_MONTHS:
        return None
    std = float(np.std(formation, ddof=1))
    if std == 0:
        return None

    return {
        "score": float(np.mean(formation) / std),
        "alpha_monthly": float(alpha),
        "beta_mkt": float(beta_mkt),
        "beta_smb": float(beta_smb),
        "beta_hml": float(beta_hml),
        "estimation_window": [window[0], window[-1]],
        "formation_window": [common[-(FORMATION_MONTHS + 1)], common[-2]],
        "n_months": len(window),
    }


def run(limit: int | None = None, on_progress=None) -> list[dict]:
    tickers = scorer.load_sp500_tickers()
    if limit:
        tickers = tickers[:limit]

    ff3 = fetch_ff3_factors()
    latest_ff3_month = max(ff3.keys())
    print(f"Fama-French factors current through {latest_ff3_month}")

    results, skipped = [], []
    for i, t in enumerate(tickers, 1):
        candles = schwab_client.get_daily_history(normalize_for_schwab_history(t))
        result = compute_residual_momentum(monthly_returns_from_candles(candles), ff3) if candles else None

        if result:
            result["ticker"] = t
            results.append(result)
            print(f"[{i}/{len(tickers)}] {t}: score={result['score']:.2f}")
        else:
            skipped.append(t)
            print(f"[{i}/{len(tickers)}] {t}: skipped (no price history or <{ESTIMATION_MONTHS}mo overlap)")

        if on_progress:
            on_progress(i, len(tickers), t)

    if skipped:
        print(f"\nSkipped {len(skipped)} tickers (no price history or <{ESTIMATION_MONTHS}mo of overlapping data): {', '.join(skipped)}")

    results.sort(key=lambda r: r["score"], reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ff3_data_through": latest_ff3_month,
        "count": len(results),
        "rows": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUTPUT_PATH}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run(args.limit)
