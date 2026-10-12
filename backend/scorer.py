"""
GARP + Momentum scoring model.

Composite 0-100 score across four buckets:
  Momentum/Trend (40) + Valuation (25) + Quality (20) + Balance sheet (15)
plus a LateLegPenalty (0-10) subtracted to produce FinalScore, and a
falling-knife hard filter that overrides the action to AVOID.

Momentum blends trend alignment, RSI zone, 52-week-high proximity, and
relative strength vs. SPY. Missing inputs score 0 on their line item
(never a "neutral" assumed value) and are recorded per-snapshot so callers
can flag a bucket as partly estimated. See
research/garp-momentum-literature-review.html for the rationale.

Originally ported from the weekly_scorecard.py prototype (Finviz-scraped,
S&P 500 constituents pulled from Wikipedia).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from typing import Dict, Optional, List, Tuple

import requests
from bs4 import BeautifulSoup

FINVIZ_QUOTE = "https://finviz.com/quote.ashx?t={ticker}"
WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GARPScorecard/1.0; +https://example.com)"
}

ALLOWED_SECTORS = {
    "Financial Services",
    "Energy",
    "Consumer Defensive",
    "Basic Materials",
    "Healthcare",
    "Utilities",
    "Industrials",
    "Real Estate",
    "Communication Services",
    "Consumer Cyclical",
    "Technology",
}


def load_sp500_tickers() -> List[str]:
    r = requests.get(WIKI_SP500, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", id="constituents")
    if table is None:
        table = soup.find("table", class_=re.compile(r"\bwikitable\b"))
    if table is None:
        raise RuntimeError("Could not find the S&P 500 constituents table on Wikipedia.")

    rows = table.find_all("tr")
    tickers: List[str] = []

    for row in rows[1:]:
        cols = row.find_all(["td", "th"])
        if not cols:
            continue
        symbol = cols[0].get_text(strip=True).upper()
        symbol = symbol.replace(" ", " ").split(" ")[0]
        tickers.append(symbol)

    seen = set()
    out: List[str] = []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def normalize_for_finviz(ticker: str) -> Optional[str]:
    t = ticker.strip().upper()
    if ".PR." in t or t.endswith(".PR.F") or "^" in t or "-P" in t:
        return None
    # Finviz wants share-class tickers dash-separated (BRK-B, BF-B), not
    # dot-separated (BRK.B, BF.B) the way Wikipedia's S&P 500 list has them.
    if "." in t:
        t = t.replace(".", "-")
    return t


def parse_percent(s: str) -> Optional[float]:
    s = s.strip().replace("%", "")
    if s in ("-", "", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_float(s: str) -> Optional[float]:
    s = s.strip()
    if s in ("-", "", "N/A"):
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_trailing_pct(s: str) -> Optional[float]:
    """
    Finviz's 52W High / 52W Low cells concatenate a price and a signed
    percent with no separator (e.g. '344.57-5.69%', '225.9543.82%').
    Extract just the trailing percent; falls back to a plain percent
    string if the layout ever changes.
    """
    s = s.strip()
    if s in ("-", "", "N/A"):
        return None
    m = re.match(r"^-?[\d,]+\.\d{2}(-?\d+\.\d{2})%$", s)
    if m:
        return float(m.group(1))
    return parse_percent(s)


def normalize_sector(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    if s == "Financial":
        s = "Financial Services"
    return s


def extract_company_name_from_title(soup: BeautifulSoup, ticker: str) -> Optional[str]:
    if not soup.title or not soup.title.string:
        return None
    title = soup.title.string.strip()

    m = re.search(rf"^{re.escape(ticker)}\s*-\s*(.*?)\s+Stock Price", title)
    if m:
        return m.group(1).strip()

    m = re.search(rf"^{re.escape(ticker)}\s*-\s*(.*?)\s+Quote", title)
    if m:
        return m.group(1).strip()

    return None


def extract_sector_from_links(soup: BeautifulSoup) -> Optional[str]:
    a = soup.find("a", href=re.compile(r"f=sec_", re.IGNORECASE))
    if a and a.get_text(strip=True):
        return a.get_text(strip=True)
    return None


@dataclass
class Snapshot:
    ticker: str
    company: Optional[str]
    price: Optional[float]
    sector: Optional[str]
    pe_ttm: Optional[float]

    fwd_pe: Optional[float]
    peg: Optional[float]
    debt_eq: Optional[float]
    current_ratio: Optional[float]
    rsi14: Optional[float]

    sma20_pct: Optional[float]
    sma50_pct: Optional[float]
    sma200_pct: Optional[float]

    perf_week_pct: Optional[float]
    perf_month_pct: Optional[float]
    perf_quarter_pct: Optional[float]

    rel_volume: Optional[float]

    pct_from_52w_high: Optional[float]
    roic: Optional[float]
    roe: Optional[float]
    profit_margin: Optional[float]


@dataclass
class Scored:
    ticker: str
    base_score: float
    momentum_score: float
    valuation_score: float
    quality_score: float
    balance_score: float

    late_leg_penalty: float
    final_score: float

    action: str
    notes: str
    missing_fields: List[str]
    snap: Snapshot

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d


# -------------- Scoring model --------------
#
# Missing inputs score 0 on their line item rather than an assumed
# "neutral" value -- score_snapshot() records which fields were missing
# so callers can flag a bucket as partly estimated instead of presenting
# a gap-filled score identically to a fully measured one.

def rsi_points(rsi: Optional[float]) -> float:
    if rsi is None:
        return 0.0
    if rsi > 70:
        return 3.0
    if 60 <= rsi <= 70:
        return 6.0
    if 50 <= rsi < 60:
        return 8.0
    if 40 <= rsi < 50:
        return 5.0
    return 0.0


def high52w_points(pct_from_high: Optional[float]) -> float:
    """8 max. Nearness to the 52-week high (George & Hwang, 2004)."""
    if pct_from_high is None:
        return 0.0
    d = abs(pct_from_high)
    if d <= 5:
        return 8.0
    if d <= 10:
        return 6.0
    if d <= 20:
        return 4.0
    if d <= 35:
        return 2.0
    return 0.0


def relative_strength_points(
    stock_month: Optional[float], spy_month: Optional[float],
    stock_quarter: Optional[float], spy_quarter: Optional[float],
) -> float:
    """8 max. Month/quarter performance relative to SPY, not absolute sign."""
    if None in (stock_month, spy_month, stock_quarter, spy_quarter):
        return 0.0
    blended = 0.5 * (stock_month - spy_month) + 0.5 * (stock_quarter - spy_quarter)
    if blended >= 10:
        return 8.0
    if blended >= 5:
        return 6.0
    if blended >= 0:
        return 4.0
    if blended >= -5:
        return 2.0
    return 0.0


def fwd_pe_points(pe: Optional[float]) -> float:
    if pe is None:
        return 0.0
    if pe <= 15:
        return 10.0
    if pe <= 25:
        return 7.0
    if pe <= 40:
        return 3.0
    return 0.0


def peg_points(peg: Optional[float]) -> float:
    if peg is None:
        return 0.0
    if peg <= 1.2:
        return 15.0
    if peg <= 1.8:
        return 9.0
    if peg <= 2.5:
        return 4.0
    return 0.0


def roic_points(roic: Optional[float]) -> float:
    """8 max. Capital-structure-neutral profitability (Novy-Marx, 2013)."""
    if roic is None:
        return 0.0
    if roic >= 20:
        return 8.0
    if roic >= 12:
        return 6.0
    if roic >= 6:
        return 3.0
    return 0.0


def roe_points(roe: Optional[float]) -> float:
    """6 max. Secondary to ROIC since buybacks can inflate ROE."""
    if roe is None:
        return 0.0
    if roe >= 20:
        return 6.0
    if roe >= 12:
        return 4.0
    if roe >= 6:
        return 2.0
    return 0.0


def profit_margin_points(pm: Optional[float]) -> float:
    if pm is None:
        return 0.0
    if pm >= 15:
        return 6.0
    if pm >= 8:
        return 4.0
    if pm >= 0:
        return 2.0
    return 0.0


def debt_points(debt_eq: Optional[float]) -> float:
    if debt_eq is None:
        return 0.0
    if debt_eq <= 0.5:
        return 10.0
    if debt_eq <= 1.0:
        return 7.0
    if debt_eq <= 2.0:
        return 3.0
    return 0.0


def current_ratio_points(cr: Optional[float]) -> float:
    if cr is None:
        return 0.0
    return 5.0 if cr >= 1.0 else 0.0


def falling_knife(s: Snapshot) -> bool:
    if s.sma200_pct is None or s.sma50_pct is None or s.rsi14 is None:
        return False
    return (s.sma200_pct < 0) and (s.sma50_pct < 0) and (s.rsi14 < 40)


def _band_penalty(value: float, bands: List[Tuple[float, float]]) -> float:
    for thr, pen in bands:
        if value < thr:
            return pen
    return bands[-1][1]


def late_leg_penalty(s: Snapshot) -> float:
    """
    Combines stretch (RSI / SMA extension), participation (rel volume vs
    momentum), and deceleration (week vs month performance) into a 0-10
    penalty subtracted from BaseScore to produce FinalScore.
    """
    stretch = 0.0
    participation = 0.0
    decel = 0.0

    if s.rsi14 is not None:
        rsi = s.rsi14
        rsi_pen = _band_penalty(rsi, [
            (65.0, 0.0), (70.0, 2.0), (75.0, 4.0),
            (80.0, 6.0), (85.0, 8.0), (10_000.0, 10.0),
        ])
        stretch = max(stretch, rsi_pen)

    if s.sma20_pct is not None:
        d20_pen = _band_penalty(s.sma20_pct, [
            (5.0, 0.0), (10.0, 2.0), (15.0, 4.0),
            (20.0, 6.0), (25.0, 8.0), (10_000.0, 10.0),
        ])
        stretch = max(stretch, d20_pen)

    if s.sma50_pct is not None:
        d50_pen = _band_penalty(s.sma50_pct, [
            (10.0, 0.0), (20.0, 1.0), (30.0, 2.0),
            (40.0, 3.0), (50.0, 4.0), (10_000.0, 5.0),
        ])
        stretch = min(10.0, stretch + 0.5 * d50_pen)

    if s.rel_volume is not None and s.rsi14 is not None:
        rv = s.rel_volume
        if s.rsi14 >= 60:
            if rv < 0.6:
                participation = 4.0
            elif rv < 0.8:
                participation = 3.0
            elif rv < 1.0:
                participation = 2.0

    if s.perf_month_pct is not None and s.perf_week_pct is not None:
        pm, pw = s.perf_month_pct, s.perf_week_pct
        if pm > 0 and pw < 0:
            decel = 3.0
        elif pm >= 6.0 and pw < (pm / 4.0):
            decel = 2.0
        if (s.rsi14 is not None) and (s.rsi14 >= 65) and (pw < 0):
            decel = min(4.0, decel + 1.0)

    penalty = stretch + participation + decel
    return max(0.0, min(10.0, penalty))


def score_snapshot(s: Snapshot, spy: Optional[Snapshot] = None) -> Scored:
    missing: List[str] = []

    def check(name: str, value: Optional[float]) -> None:
        if value is None:
            missing.append(name)

    # Momentum/Trend (40): trend alignment + RSI zone + 52W-high proximity
    # + relative strength vs SPY. No longer scores raw month/quarter sign --
    # that sat inside the short-term-reversal window and wasn't relative to
    # anything (see research/garp-momentum-literature-review.html, gap #3/#5).
    check("sma200_pct", s.sma200_pct)
    check("sma50_pct", s.sma50_pct)
    check("sma20_pct", s.sma20_pct)
    check("rsi14", s.rsi14)
    check("pct_from_52w_high", s.pct_from_52w_high)

    momentum = 0.0
    momentum += 8.0 if (s.sma200_pct is not None and s.sma200_pct > 0) else 0.0
    momentum += 4.0 if (s.sma50_pct is not None and s.sma50_pct > 0) else 0.0
    momentum += 4.0 if (s.sma20_pct is not None and s.sma20_pct > 0) else 0.0
    momentum += rsi_points(s.rsi14)
    momentum += high52w_points(s.pct_from_52w_high)

    spy_month = spy.perf_month_pct if spy else None
    spy_quarter = spy.perf_quarter_pct if spy else None
    if spy is None or spy_month is None or spy_quarter is None:
        missing.append("relative_strength")
    else:
        check("perf_month_pct", s.perf_month_pct)
        check("perf_quarter_pct", s.perf_quarter_pct)
    momentum += relative_strength_points(s.perf_month_pct, spy_month, s.perf_quarter_pct, spy_quarter)
    momentum = min(momentum, 40.0)

    # Valuation (25): Forward P/E + PEG
    check("fwd_pe", s.fwd_pe)
    check("peg", s.peg)
    valuation = min(fwd_pe_points(s.fwd_pe) + peg_points(s.peg), 25.0)

    # Quality (20): profitability, capital-structure-neutral first (Novy-Marx; Piotroski)
    check("roic", s.roic)
    check("roe", s.roe)
    check("profit_margin", s.profit_margin)
    quality = min(roic_points(s.roic) + roe_points(s.roe) + profit_margin_points(s.profit_margin), 20.0)

    # Balance sheet (15): solvency only -- quality bucket above covers profitability
    check("debt_eq", s.debt_eq)
    check("current_ratio", s.current_ratio)
    balance = min(debt_points(s.debt_eq) + current_ratio_points(s.current_ratio), 15.0)

    base_total = momentum + valuation + quality + balance
    penalty = late_leg_penalty(s)
    final_total = max(0.0, base_total - penalty)

    if falling_knife(s):
        action, notes = "AVOID", "Falling-knife filter triggered"
    elif final_total >= 80:
        action, notes = "BUY/ADD", "A-grade alignment"
    elif final_total >= 65:
        action, notes = "BUY", "B-grade; confirm entry trigger"
    elif final_total >= 50:
        action, notes = "WATCH", "Needs inflection trigger"
    else:
        action, notes = "AVOID", "Not aligned this week"

    return Scored(
        ticker=s.ticker,
        base_score=base_total,
        momentum_score=momentum,
        valuation_score=valuation,
        quality_score=quality,
        balance_score=balance,
        late_leg_penalty=penalty,
        final_score=final_total,
        action=action,
        notes=notes,
        missing_fields=missing,
        snap=s,
    )


# -------------- Finviz fetch --------------

def fetch_finviz_snapshot(ticker: str, sleep_s: float = 0.7) -> Optional[Snapshot]:
    url = FINVIZ_QUOTE.format(ticker=ticker)
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    # Finviz splits the stats grid across several <table class="snapshot-table2">
    # fragments (was a single table in earlier layouts) -- merge them all.
    tables = soup.find_all("table", class_="snapshot-table2")
    if not tables:
        return None

    raw: Dict[str, str] = {}
    for table in tables:
        cells = [c.get_text(strip=True) for c in table.find_all("td")]
        for i in range(0, len(cells) - 1, 2):
            raw[cells[i]] = cells[i + 1]

    def g(key: str) -> Optional[str]:
        return raw.get(key)

    company = extract_company_name_from_title(soup, ticker)
    sector = normalize_sector(extract_sector_from_links(soup))

    snap = Snapshot(
        ticker=ticker,
        company=company,
        price=parse_float(g("Price") or "-"),
        sector=sector,
        pe_ttm=parse_float(g("P/E") or "-"),

        fwd_pe=parse_float(g("Forward P/E") or "-"),
        peg=parse_float(g("PEG") or "-"),
        debt_eq=parse_float(g("Debt/Eq") or "-"),
        current_ratio=parse_float(g("Current Ratio") or "-"),
        rsi14=parse_float(g("RSI (14)") or "-"),

        sma20_pct=parse_percent(g("SMA20") or "-"),
        sma50_pct=parse_percent(g("SMA50") or "-"),
        sma200_pct=parse_percent(g("SMA200") or "-"),

        perf_week_pct=parse_percent(g("Perf Week") or "-"),
        perf_month_pct=parse_percent(g("Perf Month") or "-"),
        perf_quarter_pct=parse_percent(g("Perf Quarter") or "-"),

        rel_volume=parse_float(g("Rel Volume") or "-"),

        pct_from_52w_high=parse_trailing_pct(g("52W High") or "-"),
        roic=parse_percent(g("ROIC") or "-"),
        roe=parse_percent(g("ROE") or "-"),
        profit_margin=parse_percent(g("Profit Margin") or "-"),
    )

    time.sleep(sleep_s)
    return snap
