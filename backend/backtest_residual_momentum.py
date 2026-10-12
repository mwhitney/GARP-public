"""
Backtest: does residual momentum predict next-month returns across this app's
universe, and does it add anything beyond the app's own Momentum bucket?

Everything is rebuilt point-in-time from Schwab daily price history -- each
signal at month-end t uses only data available at t -- then scored against
what the stock actually did next. Only price-derived signals can be tested
this way (momentum, residual momentum, the Momentum bucket); the Valuation /
Quality / Balance buckets need point-in-time fundamentals this app doesn't have.

Signals compared, each ranked into quintiles every month:
  * Residual momentum   -- exactly the live implementation (36-mo Fama-French
                           regression, mean/stdev of the 12-1 residuals)
  * Raw 12-1 momentum   -- plain cumulative return, months t-12..t-1
  * Momentum bucket     -- the app's 0-40 bucket, rebuilt from daily prices
                           using scorer.py's own band functions
  * Bucket + RM tilt    -- bucket plus the +/-4 "Design A" tilt

Known limitations, all of which flatter or distort in some direction:
  * Survivorship bias: the universe is TODAY's S&P 500 constituents.
  * Price returns only (no dividends), no transaction costs, equal-weighted.
  * Fama-French data lags ~2 months in live use; the "as-used" run (lag=2)
    skips a month to mimic that.

Usage:
  python backend/backtest_residual_momentum.py fetch [--limit N]
  python backend/backtest_residual_momentum.py run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scorer  # noqa: E402
import schwab_client  # noqa: E402
import residual_momentum as rm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "backtest_cache.json"
RESULT_PATH = ROOT / "data" / "backtest_residual_momentum.json"
CACHE_FROM = "200401"
FEATURES = ["close", "s20", "s50", "s200", "rsi", "h52"]
TEST_START = "2008-01"


# ---------------------------------------------------------------- fetch

def month_end_table(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["date"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    c, h = df["close"], df["high"]
    df["s20"] = (c / c.rolling(20).mean() - 1) * 100
    df["s50"] = (c / c.rolling(50).mean() - 1) * 100
    df["s200"] = (c / c.rolling(200).mean() - 1) * 100
    df["h52"] = (c / h.rolling(252).max() - 1) * 100
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)
    df["ym"] = df["date"].dt.strftime("%Y%m")
    me = df.drop_duplicates("ym", keep="last").set_index("ym")[FEATURES]
    current = datetime.now(timezone.utc).strftime("%Y%m")
    return me[(me.index >= CACHE_FROM) & (me.index < current)]  # drop the unfinished month


def fetch(limit: int | None) -> None:
    tickers = scorer.load_sp500_tickers()
    if limit:
        tickers = tickers[:limit]
    tickers = ["SPY"] + [t for t in tickers if t != "SPY"]

    data, skipped = {}, []
    for i, t in enumerate(tickers, 1):
        candles = schwab_client.get_daily_history(rm.normalize_for_schwab_history(t))
        if not candles or len(candles) < 300:
            skipped.append(t)
            print(f"[{i}/{len(tickers)}] {t}: skipped")
            continue
        me = month_end_table(candles)
        data[t] = {
            ym: [None if pd.isna(v) else round(float(v), 4) for v in row]
            for ym, row in zip(me.index, me.to_numpy())
        }
        print(f"[{i}/{len(tickers)}] {t}: {len(me)} month-ends")

    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data}))
    print(f"\nCached {len(data)} tickers -> {CACHE_PATH}  (skipped {len(skipped)}: {', '.join(skipped)})")


# ---------------------------------------------------------------- panel + signals

def load_panel():
    raw = json.loads(CACHE_PATH.read_text())["data"]
    frames = {}
    for k, feat in enumerate(FEATURES):
        f = pd.DataFrame({t: {ym: v[k] for ym, v in months.items()} for t, months in raw.items()}).astype(float)
        f.index = pd.PeriodIndex(f.index, freq="M")
        frames[feat] = f.sort_index()
    full = pd.period_range(frames["close"].index.min(), frames["close"].index.max(), freq="M")
    frames = {k: v.reindex(full) for k, v in frames.items()}

    # Schwab's history is split-adjusted but also has large SPECIAL dividends
    # subtracted from old prices, which can push a series to zero or negative
    # (COST, TDG, PCAR, ...). Returns off those series are nonsense, so drop them.
    corrupted = [t for t in frames["close"].columns if t != "SPY" and (frames["close"][t] <= 0).any()]
    frames = {k: v.drop(columns=corrupted) for k, v in frames.items()}
    frames["_corrupted"] = corrupted
    return frames


def compute_rm(ret: pd.DataFrame, ff: pd.DataFrame) -> pd.DataFrame:
    months = ret.index
    out = pd.DataFrame(np.nan, index=months, columns=ret.columns)
    ffa = ff.reindex(months)
    excess = ret.sub(ffa["rf"], axis=0)
    for i in range(rm.ESTIMATION_MONTHS - 1, len(months)):
        win = slice(i - rm.ESTIMATION_MONTHS + 1, i + 1)
        F = ffa.iloc[win][["mkt_rf", "smb", "hml"]]
        if F.isna().any().any():
            continue
        Y = excess.iloc[win]
        valid = Y.notna().all(axis=0).to_numpy()
        if valid.sum() < 50:
            continue
        X = np.column_stack([np.ones(rm.ESTIMATION_MONTHS), F.to_numpy()])
        Yv = Y.to_numpy()[:, valid]
        coef, *_ = np.linalg.lstsq(X, Yv, rcond=None)
        form = (Yv - X @ coef)[-(rm.FORMATION_MONTHS + 1):-1]
        sd = form.std(axis=0, ddof=1)
        score = np.where(sd > 0, form.mean(axis=0) / np.where(sd > 0, sd, 1), np.nan)
        out.iloc[i, np.flatnonzero(valid)] = score
    return out


def compute_raw_12_1(ret: pd.DataFrame) -> pd.DataFrame:
    return (1 + ret).rolling(12).apply(np.prod, raw=True).shift(1) - 1


def compute_bucket(p: dict, ret: pd.DataFrame, spy_close: pd.Series) -> pd.DataFrame:
    close = p["close"]
    pm = ret * 100
    pq = (close / close.shift(3) - 1) * 100
    spy_pm = (spy_close.pct_change(fill_method=None) * 100).to_numpy()
    spy_pq = ((spy_close / spy_close.shift(3) - 1) * 100).to_numpy()
    arr = {k: p[k].to_numpy() for k in ("s20", "s50", "s200", "rsi", "h52")}
    pm_a, pq_a = pm.to_numpy(), pq.to_numpy()
    out = np.full(close.shape, np.nan)
    for i in range(close.shape[0]):
        for j in range(close.shape[1]):
            vals = (arr["s20"][i, j], arr["s50"][i, j], arr["s200"][i, j], arr["rsi"][i, j],
                    arr["h52"][i, j], pm_a[i, j], pq_a[i, j], spy_pm[i], spy_pq[i])
            if any(np.isnan(v) for v in vals):
                continue
            s20, s50, s200, rsi, h52, m, q, sm, sq = vals
            pts = (8.0 if s200 > 0 else 0.0) + (4.0 if s50 > 0 else 0.0) + (4.0 if s20 > 0 else 0.0)
            pts += scorer.rsi_points(rsi) + scorer.high52w_points(h52)
            pts += scorer.relative_strength_points(m, sm, q, sq)
            out[i, j] = min(pts, 40.0)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


def rm_tilt(score: pd.DataFrame) -> pd.DataFrame:
    t = score * math.sqrt(12)
    tilt = np.select([t >= 2, t >= 1, t <= -2, t <= -1], [4.0, 2.0, -4.0, -2.0], default=0.0)
    return pd.DataFrame(tilt, index=score.index, columns=score.columns).where(score.notna())


# ---------------------------------------------------------------- tests

def spread_stats(s: pd.Series) -> dict:
    n, mean, sd = len(s), s.mean(), s.std(ddof=1)
    return {
        "n": n, "mean": mean, "t": mean / (sd / math.sqrt(n)), "sharpe": mean / sd * math.sqrt(12),
        "pos": (s > 0).mean() * 100, "worst": s.min(), "worst_month": str(s.idxmin()),
    }


def sort_test(signal: pd.DataFrame, fwd: pd.DataFrame, mask: pd.DataFrame, months, groups=5, seed=0):
    rng = np.random.RandomState(seed)
    rows, spreads = [], {}
    for t in months:
        m = mask.loc[t]
        if m.sum() < 100:
            continue
        s = signal.loc[t][m] + rng.uniform(0, 1e-6, m.sum())  # break ties (the bucket is discrete)
        f = fwd.loc[t][m] * 100
        g = pd.qcut(s.rank(method="first"), groups, labels=False)
        means = f.groupby(g).mean()
        rows.append(means.rename(t))
    q = pd.DataFrame(rows)
    return q, q[groups - 1] - q[0]


def fama_macbeth(signals: dict[str, pd.DataFrame], fwd: pd.DataFrame, mask: pd.DataFrame, months) -> dict:
    names = list(signals)
    coefs = []
    for t in months:
        m = mask.loc[t]
        if m.sum() < 100:
            continue
        cols = []
        for n in names:
            x = signals[n].loc[t][m]
            cols.append(((x - x.mean()) / x.std(ddof=0)).to_numpy())
        X = np.column_stack([np.ones(m.sum())] + cols)
        y = (fwd.loc[t][m] * 100).to_numpy()
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        coefs.append(b[1:])
    c = np.array(coefs)
    mean, se = c.mean(axis=0), c.std(axis=0, ddof=1) / math.sqrt(len(c))
    return {n: {"coef": float(mean[k]), "t": float(mean[k] / se[k])} for k, n in enumerate(names)}


def winsorize(df: pd.DataFrame, lo=0.01, hi=0.99) -> pd.DataFrame:
    return df.clip(lower=df.quantile(lo, axis=1), upper=df.quantile(hi, axis=1), axis=0)


def tstat(s: pd.Series) -> float:
    return s.mean() / (s.std(ddof=1) / math.sqrt(len(s)))


def run() -> None:
    p = load_panel()
    corrupted = p.pop("_corrupted")
    print(f"excluded {len(corrupted)} tickers with corrupted (non-positive) adjusted prices: {', '.join(corrupted)}")
    spy_close = p["close"]["SPY"]
    stocks = {k: v.drop(columns=["SPY"]) for k, v in p.items()}
    close = stocks["close"]
    ret = close.pct_change(fill_method=None)

    ff_raw = rm.fetch_ff3_factors()
    ff = pd.DataFrame(ff_raw).T
    ff.index = pd.PeriodIndex(ff.index, freq="M")

    print("building signals ...")
    rm_score = compute_rm(ret, ff)
    raw = compute_raw_12_1(ret)
    bucket = compute_bucket(stocks, ret, spy_close)
    bucket_tilt = bucket + rm_tilt(rm_score).fillna(0)

    # parity check against the live dashboard numbers at the latest month with factor data
    live = {r["ticker"]: r["score"] for r in json.loads(rm.OUTPUT_PATH.read_text())["rows"]}
    last = rm_score.dropna(how="all").index[-1]
    diffs = [abs(rm_score.loc[last, t] - s) for t, s in live.items() if t in rm_score.columns and pd.notna(rm_score.loc[last, t])]
    print(f"parity vs live residual_momentum.json at {last}: {len(diffs)} tickers compared, max abs diff {max(diffs):.2e}")

    signals = {
        "Residual momentum": rm_score,
        "Raw 12-1 momentum": raw,
        "Momentum bucket (0-40)": bucket,
        "Bucket + RM tilt": bucket_tilt,
    }
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "lags": {}}

    for lag in (1, 2):
        fwd = ret.shift(-lag)
        mask = rm_score.notna() & raw.notna() & bucket.notna() & fwd.notna()
        months = [t for t in rm_score.index if str(t) >= TEST_START and mask.loc[t].sum() >= 100]
        avg_n = np.mean([mask.loc[t].sum() for t in months])
        label = "ideal timing: signal at t, hold month t+1" if lag == 1 else "as used live: factor data lags, so hold month t+2"
        print(f"\n{'=' * 78}\nLAG {lag} ({label})\n{months[0]} .. {months[-1]}  |  {len(months)} months, ~{avg_n:.0f} stocks/month\n{'=' * 78}")
        print(f"{'signal':26s} {'Q1':>6s} {'Q2':>6s} {'Q3':>6s} {'Q4':>6s} {'Q5':>6s} | {'Q5-Q1':>6s} {'t':>5s} {'Sharpe':>6s} {'%pos':>5s} {'worst':>7s}")
        lag_res = {}
        spreads = {}
        for name, sig in signals.items():
            q, spread = sort_test(sig, fwd, mask, months)
            st = spread_stats(spread)
            spreads[name] = spread
            lag_res[name] = {"quintile_means": q.mean().round(3).tolist(), **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items()}}
            qm = q.mean()
            print(f"{name:26s} " + " ".join(f"{qm[k]:6.2f}" for k in range(5)) +
                  f" | {st['mean']:6.2f} {st['t']:5.1f} {st['sharpe']:6.2f} {st['pos']:5.0f} {st['worst']:7.1f}  ({st['worst_month']})")

        print("\n  robustness, Q5-Q1 %/mo (t):  baseline | winsorized 1/99 | deciles D10-D1 | excluding 2009")
        fwd_w = winsorize(fwd)
        months_x09 = [t for t in months if t.year != 2009]
        lag_res["robustness"] = {}
        for name in ("Residual momentum", "Raw 12-1 momentum", "Momentum bucket (0-40)"):
            cells = []
            for f, ms, g in ((fwd, months, 5), (fwd_w, months, 5), (fwd, months, 10), (fwd, months_x09, 5)):
                _, sp = sort_test(signals[name], f, mask, ms, groups=g)
                cells.append((float(sp.mean()), float(tstat(sp))))
            lag_res["robustness"][name] = cells
            print(f"    {name:24s} " + " | ".join(f"{m:+5.2f} ({t:+4.1f})" for m, t in cells))

        if lag == 1:
            d = spreads["Bucket + RM tilt"] - spreads["Momentum bucket (0-40)"]
            n = len(d)
            print(f"\n  adding the +/-4 tilt to the bucket: spread change {d.mean():+.3f} %/mo (t = {d.mean() / (d.std(ddof=1) / math.sqrt(n)):+.2f})")

            third = len(months) // 3
            print("\n  sub-periods (Q5-Q1 spread %/mo, t):")
            for name in ("Residual momentum", "Raw 12-1 momentum", "Momentum bucket (0-40)"):
                parts = []
                for lo, hi in ((0, third), (third, 2 * third), (2 * third, len(months))):
                    ms = months[lo:hi]
                    s = spreads[name].reindex(ms).dropna()
                    parts.append(f"{ms[0]}..{ms[-1]}: {s.mean():+5.2f} (t {s.mean() / (s.std(ddof=1) / math.sqrt(len(s))):+.1f})")
                print(f"    {name:24s} " + " | ".join(parts))

            print("\n  incremental information (Fama-MacBeth, %/mo per 1 s.d. of signal):")
            fm = {}
            for label_, combo in (("RM alone", ["Residual momentum"]),
                                  ("Bucket alone", ["Momentum bucket (0-40)"]),
                                  ("Raw 12-1 alone", ["Raw 12-1 momentum"]),
                                  ("RM + Bucket", ["Residual momentum", "Momentum bucket (0-40)"]),
                                  ("RM + Raw 12-1", ["Residual momentum", "Raw 12-1 momentum"])):
                r = fama_macbeth({n: signals[n] for n in combo}, fwd, mask, months)
                fm[label_] = r
                print(f"    {label_:16s} " + "   ".join(f"{n.split(' (')[0]}: {v['coef']:+.3f} (t {v['t']:+.1f})" for n, v in r.items()))
            lag_res["fama_macbeth"] = fm
        result["lags"][str(lag)] = lag_res

    RESULT_PATH.write_text(json.dumps(result, indent=2, default=float))
    print(f"\nwrote {RESULT_PATH}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "run"])
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    fetch(a.limit) if a.cmd == "fetch" else run()
