"""
Generate the fictional demo dataset embedded in dashboard/template.html.

Everything here is invented: companies, tickers, prices, and every metric.
Raw metrics are drawn from archetype-shaped ranges, then run through the
REAL scoring model (scorer.score_snapshot), so buckets, penalties, actions,
the falling-knife override, and the "~ est." missing-data flags all behave
exactly as they do on live data.

Deterministic (fixed seed): re-running rewrites the same block.

Usage:
  python backend/make_demo_data.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scorer  # noqa: E402
from server import _position_flag  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "dashboard" / "template.html"
SEED = 20260115
GENERATED_AT = "2026-10-12T14:00:00+00:00"  # fictional, only affects the unused generated_at field

# (ticker, company, sector, archetype)
UNIVERSE = [
    # Technology
    ("NVLK", "Novalink Systems", "Technology", "momentum_leader"),
    ("QRTZ", "Quartzline Software", "Technology", "quality_compounder"),
    ("HLNX", "Helixnet Semiconductor", "Technology", "momentum_leader"),
    ("PXLR", "Pixelrow Interactive", "Technology", "overextended"),
    ("DTRV", "Datarive Analytics", "Technology", "quality_compounder"),
    ("BYTW", "Bytewell Hardware", "Technology", "value_cheap"),
    ("CLDF", "Cloudfern Platforms", "Technology", "balanced"),
    ("ZNTH", "Zenthra Security", "Technology", "momentum_leader"),
    ("ORBT", "Orbitrail Networks", "Technology", "turnaround"),
    ("LMNR", "Lumenra Photonics", "Technology", "balanced"),
    # Healthcare
    ("VRTB", "Vertebra Biologics", "Healthcare", "momentum_leader"),
    ("CLRX", "Clearbrook Pharma", "Healthcare", "value_cheap"),
    ("PLSE", "Pulsewell Diagnostics", "Healthcare", "quality_compounder"),
    ("ANVL", "Anvilmed Devices", "Healthcare", "defensive"),
    ("GNMX", "Genomex Therapeutics", "Healthcare", "falling_knife"),
    ("CRDL", "Cardiolink Health", "Healthcare", "balanced"),
    ("BRCH", "Birchwood Care Services", "Healthcare", "turnaround"),
    # Financial Services
    ("HRBR", "Harborline Bancorp", "Financial Services", "value_cheap"),
    ("PNCL", "Pinnacrest Financial", "Financial Services", "balanced"),
    ("TRSL", "Trustleaf Insurance", "Financial Services", "defensive"),
    ("LDGR", "Ledgerton Asset Management", "Financial Services", "quality_compounder"),
    ("CRDT", "Creditvale Lending", "Financial Services", "knife_quality"),
    ("MRKT", "Marketstone Exchange", "Financial Services", "momentum_leader"),
    ("SLVR", "Silverbrook Savings", "Financial Services", "value_cheap"),
    ("UNMR", "Undermark Reinsurance", "Financial Services", "overextended"),
    # Industrials
    ("FRGE", "Forgeway Industrial", "Industrials", "balanced"),
    ("TRNS", "Transvale Logistics", "Industrials", "turnaround"),
    ("RVTX", "Rivetex Machinery", "Industrials", "value_cheap"),
    ("WNDR", "Windrow Aerospace", "Industrials", "momentum_leader"),
    ("GRDN", "Gridnorth Electrical", "Industrials", "quality_compounder"),
    ("CNVY", "Conveyra Systems", "Industrials", "balanced"),
    ("HVYL", "Heavyline Equipment", "Industrials", "defensive"),
    # Consumer Cyclical
    ("VYGR", "Voyagerly Travel", "Consumer Cyclical", "momentum_leader"),
    ("AUTV", "Autovale Motors", "Consumer Cyclical", "knife_quality"),
    ("HMST", "Homestead Furnishings", "Consumer Cyclical", "value_cheap"),
    ("SNKR", "Sneakerly Brands", "Consumer Cyclical", "overextended"),
    ("BRGR", "Burgerton Restaurants", "Consumer Cyclical", "balanced"),
    ("LXLN", "Luxeline Retail", "Consumer Cyclical", "turnaround"),
    # Consumer Defensive
    ("PNTR", "Pantryline Foods", "Consumer Defensive", "defensive"),
    ("DLYS", "Dairylane Cooperative", "Consumer Defensive", "defensive"),
    ("HYGX", "Hygienix Household", "Consumer Defensive", "quality_compounder"),
    ("BVRG", "Beveridge Beverages", "Consumer Defensive", "balanced"),
    ("GRCR", "Grocerly Markets", "Consumer Defensive", "value_cheap"),
    # Energy
    ("NRTH", "Northgate Petroleum", "Energy", "value_cheap"),
    ("SNRG", "Sunridge Renewables", "Energy", "momentum_leader"),
    ("DPWL", "Deepwell Drilling", "Energy", "turnaround"),
    ("RDGL", "Ridgeline Midstream", "Energy", "quality_compounder"),
    ("TDMK", "Tidemark Offshore", "Energy", "falling_knife"),
    # Utilities
    ("ELGD", "Electra Grid Utilities", "Utilities", "defensive"),
    ("AQVL", "Aquavale Water", "Utilities", "defensive"),
    ("GSLT", "Gaslight Distribution", "Utilities", "leveraged"),
    ("WNGP", "Windgate Power", "Utilities", "balanced"),
    # Real Estate
    ("STWL", "Storewell Self-Storage REIT", "Real Estate", "defensive"),
    ("OFLN", "Officeline Properties", "Real Estate", "falling_knife"),
    ("APMK", "Aptmark Residential", "Real Estate", "leveraged"),
    ("LGCR", "Logisticore Industrial REIT", "Real Estate", "quality_compounder"),
    # Basic Materials
    ("CPFD", "Copperfield Mining", "Basic Materials", "momentum_leader"),
    ("CHVL", "Chemvale Specialty", "Basic Materials", "balanced"),
    ("STMK", "Steelmark Alloys", "Basic Materials", "value_cheap"),
    # Communication Services
    ("SLRK", "Streamlark Media", "Communication Services", "overextended"),
    ("TLCT", "Telecomet Wireless", "Communication Services", "defensive"),
    ("ADWV", "Adwave Digital", "Communication Services", "turnaround"),
    ("SCNS", "Socialnest", "Communication Services", "balanced"),
]

# Raw-metric ranges per archetype, so the scoring model produces a realistic
# spread of outcomes rather than a wall of identical scores.
ARCH = {
    "momentum_leader":   dict(roic=(14, 26), roe=(16, 32), margin=(12, 24), debt=(0.2, 1.0), cur=(1.1, 2.4), fpe=(20, 36), peg=(1.0, 1.9),
                              rsi=(58, 70), s200=(14, 38), s50=(7, 20), s20=(3, 10), pw=(0, 4), pm=(5, 15), pq=(14, 34), h52=(-4, 0), rv=(0.9, 1.7)),
    "quality_compounder": dict(roic=(18, 34), roe=(20, 38), margin=(18, 32), debt=(0.1, 0.7), cur=(1.5, 3.0), fpe=(18, 30), peg=(1.2, 2.1),
                               rsi=(52, 64), s200=(8, 22), s50=(3, 11), s20=(1, 6), pw=(-1, 3), pm=(2, 9), pq=(6, 18), h52=(-8, -1), rv=(0.8, 1.3)),
    "value_cheap":       dict(roic=(10, 20), roe=(12, 24), margin=(8, 16), debt=(0.2, 1.0), cur=(1.0, 2.2), fpe=(8, 14), peg=(0.5, 1.1),
                              rsi=(42, 56), s200=(-8, 8), s50=(-5, 5), s20=(-4, 3), pw=(-2, 2), pm=(-4, 4), pq=(-6, 8), h52=(-30, -8), rv=(0.7, 1.2)),
    "balanced":          dict(roic=(7, 15), roe=(9, 19), margin=(6, 13), debt=(0.5, 1.6), cur=(0.9, 1.9), fpe=(15, 26), peg=(1.5, 2.6),
                              rsi=(44, 58), s200=(-6, 10), s50=(-4, 6), s20=(-3, 4), pw=(-2, 3), pm=(-4, 6), pq=(-5, 12), h52=(-18, -4), rv=(0.7, 1.3)),
    "defensive":         dict(roic=(7, 13), roe=(9, 17), margin=(8, 15), debt=(0.8, 1.9), cur=(0.8, 1.6), fpe=(14, 22), peg=(2.0, 3.6),
                              rsi=(40, 54), s200=(-6, 5), s50=(-4, 3), s20=(-3, 2), pw=(-2, 1), pm=(-4, 2), pq=(-4, 5), h52=(-20, -8), rv=(0.6, 1.1)),
    "overextended":      dict(roic=(12, 24), roe=(15, 30), margin=(10, 22), debt=(0.3, 1.2), cur=(1.0, 2.2), fpe=(26, 48), peg=(1.8, 3.2),
                              rsi=(67, 79), s200=(28, 60), s50=(15, 34), s20=(5, 15), pw=(-3, 3), pm=(5, 20), pq=(16, 50), h52=(-3, 0), rv=(0.6, 1.4)),
    "turnaround":        dict(roic=(2, 9), roe=(3, 11), margin=(1, 8), debt=(0.8, 2.0), cur=(0.9, 1.7), fpe=(12, 26), peg=(1.5, 3.0),
                              rsi=(46, 58), s200=(-4, 4), s50=(-1, 6), s20=(0, 4), pw=(-1, 3), pm=(0, 8), pq=(-2, 10), h52=(-22, -10), rv=(0.8, 1.5)),
    "falling_knife":     dict(roic=(-3, 7), roe=(-6, 8), margin=(-6, 5), debt=(1.2, 3.0), cur=(0.6, 1.2), fpe=(16, 40), peg=(2.0, 4.5),
                              rsi=(24, 38), s200=(-26, -8), s50=(-18, -5), s20=(-10, -2), pw=(-5, 0), pm=(-14, -3), pq=(-30, -8), h52=(-60, -30), rv=(1.0, 2.2)),
    "knife_quality":     dict(roic=(14, 26), roe=(16, 30), margin=(12, 22), debt=(0.2, 0.9), cur=(1.2, 2.4), fpe=(9, 15), peg=(0.6, 1.2),
                              rsi=(28, 38), s200=(-20, -6), s50=(-14, -3), s20=(-8, -1), pw=(-4, 1), pm=(-10, -2), pq=(-24, -6), h52=(-45, -25), rv=(1.0, 1.8)),
    "leveraged":         dict(roic=(5, 10), roe=(8, 16), margin=(10, 18), debt=(2.0, 4.0), cur=(0.5, 0.95), fpe=(13, 20), peg=(2.2, 4.0),
                              rsi=(42, 56), s200=(-4, 6), s50=(-3, 4), s20=(-2, 3), pw=(-2, 2), pm=(-3, 4), pq=(-3, 7), h52=(-16, -6), rv=(0.6, 1.1)),
}

# Recently listed in the story: no 36 months of history, so no residual-momentum score.
NO_RESIDUAL = {"ZNTH", "SNRG", "ADWV"}
# Deterministic missing-data cases so the "~ est." badges and "(missing)" stats show up.
FORCE_NO_PEG = {"BRCH", "CRDT", "TDMK", "ORBT", "STWL"}
FORCE_NO_DEBT = {"LGCR", "MRKT"}
FORCE_NO_ROE = {"APMK"}
FORCE_NO_SMA200 = {"ZNTH"}   # listed < 200 trading days ago


def u(rng: random.Random, span: tuple[float, float], nd: int = 2) -> float:
    return round(rng.uniform(*span), nd)


def make_snapshot(rng: random.Random, ticker: str, company: str, sector: str, arch: str) -> scorer.Snapshot:
    a = ARCH[arch]
    fwd_pe = u(rng, a["fpe"], 1)
    peg = u(rng, a["peg"])
    debt = u(rng, a["debt"])
    roe = u(rng, a["roe"], 1)
    if arch in ("falling_knife", "turnaround") and rng.random() < 0.4:
        fwd_pe = None  # negative / unavailable forward earnings
    if ticker in FORCE_NO_PEG or fwd_pe is None:
        peg = None
    if ticker in FORCE_NO_DEBT:
        debt = None
    if ticker in FORCE_NO_ROE:
        roe = None
    sma200 = None if ticker in FORCE_NO_SMA200 else u(rng, a["s200"], 1)
    return scorer.Snapshot(
        ticker=ticker, company=company, sector=sector,
        price=round(10 ** rng.uniform(1.2, 2.8), 2),
        pe_ttm=round(fwd_pe * rng.uniform(1.0, 1.4), 2) if fwd_pe else None,
        fwd_pe=fwd_pe, peg=peg, debt_eq=debt, current_ratio=u(rng, a["cur"]),
        rsi14=u(rng, a["rsi"], 1),
        sma20_pct=u(rng, a["s20"], 1), sma50_pct=u(rng, a["s50"], 1), sma200_pct=sma200,
        perf_week_pct=u(rng, a["pw"], 1), perf_month_pct=u(rng, a["pm"], 1), perf_quarter_pct=u(rng, a["pq"], 1),
        rel_volume=u(rng, a["rv"]),
        pct_from_52w_high=u(rng, a["h52"], 1),
        roic=u(rng, a["roic"], 1), roe=roe, profit_margin=u(rng, a["margin"], 1),
    )


def make_residual(rng: random.Random, ticker: str, sector: str, arch: str) -> dict:
    centre = {"momentum_leader": 0.25, "quality_compounder": 0.15, "value_cheap": 0.0, "overextended": -0.1,
              "falling_knife": -0.5, "knife_quality": -0.4, "turnaround": -0.05, "defensive": -0.05, "balanced": 0.0, "leveraged": -0.1}[arch]
    beta_mkt = {"momentum_leader": (1.2, 1.9), "overextended": (1.4, 2.2), "defensive": (0.3, 0.8),
                "falling_knife": (1.0, 1.7), "knife_quality": (0.9, 1.4)}.get(arch, (0.7, 1.3))
    if sector == "Utilities":
        beta_mkt = (0.2, 0.6)
    hml = rng.gauss(-0.8, 0.5) if arch in ("momentum_leader", "overextended", "quality_compounder") else \
        rng.gauss(0.6, 0.5) if arch in ("value_cheap", "defensive", "leveraged") else rng.gauss(0.0, 0.5)
    return {
        "ticker": ticker,
        "score": round(max(-1.1, min(0.8, rng.gauss(centre, 0.3))), 4),
        "alpha_monthly": round(rng.gauss(0.004, 0.01), 5),
        "beta_mkt": round(rng.uniform(*beta_mkt), 4),
        "beta_smb": round(max(-1.2, min(1.2, rng.gauss(-0.2, 0.5))), 4),
        "beta_hml": round(hml, 4),
        "estimation_window": ["202309", "202608"],
        "formation_window": ["202508", "202607"],
        "n_months": 36,
    }


# (ticker, unrealized %, account last4, account type, quantity)
PORTFOLIO = [
    ("NVLK", 58.0, "0002", "MARGIN", 120),   # up 40%+            -> profit-take watch
    ("PXLR", 27.0, "0002", "MARGIN", 75),    # up 20%+ AND stretched (penalty >= 6) -> profit-take watch
    ("QRTZ", 24.0, "0002", "MARGIN", 85),    # up 20%+ but not stretched            -> no flag
    ("GNMX", -24.0, "0002", "MARGIN", 200),
    ("HRBR", -17.0, "0001", "CASH", 140),
    ("CNVY", 7.0, "0001", "CASH", 55),
    ("PNTR", -4.0, "0001", "CASH", 90),
]
DEMO_ETFS = [
    ("DMOT", "Demo Total Market Index ETF", 61.0, "0001", "CASH", 38.5),
    ("DMDG", "Demo Dividend Growth ETF", 27.0, "0001", "CASH", 52.0),
    ("DMOB", "Demo Short-Term Treasury ETF", 1.5, "0002", "MARGIN", 140.0),
]


def build() -> dict:
    rng = random.Random(SEED)
    spy = scorer.Snapshot(
        ticker="SPY", company="Demo market benchmark", price=500.0, sector=None, pe_ttm=None, fwd_pe=None, peg=None,
        debt_eq=None, current_ratio=None, rsi14=55.0, sma20_pct=1.0, sma50_pct=2.5, sma200_pct=7.0,
        perf_week_pct=0.4, perf_month_pct=1.5, perf_quarter_pct=4.0, rel_volume=1.0, pct_from_52w_high=-2.0,
        roic=None, roe=None, profit_margin=None)

    rows, rm_rows = [], []
    for ticker, company, sector, arch in UNIVERSE:
        snap = make_snapshot(rng, ticker, company, sector, arch)
        rows.append(scorer.score_snapshot(snap, spy=spy).to_dict())
        resid = make_residual(rng, ticker, sector, arch)  # always draw so the RNG stream is stable
        if ticker not in NO_RESIDUAL:
            rm_rows.append(resid)
    rows.sort(key=lambda r: r["final_score"], reverse=True)
    rm_rows.sort(key=lambda r: r["score"], reverse=True)
    by_ticker = {r["ticker"]: r for r in rows}

    positions = []
    for symbol, pct, last4, acct_type, qty in PORTFOLIO:
        row = by_ticker[symbol]
        price = row["snap"]["price"]
        avg = round(price / (1 + pct / 100), 2)
        value = round(qty * price, 2)
        gl = round(value - qty * avg, 2)
        positions.append({
            "account_last4": last4, "account_type": acct_type, "symbol": symbol,
            "description": row["snap"]["company"].upper(), "asset_type": "EQUITY",
            "quantity": qty, "average_price": avg, "current_price": price, "market_value": value,
            "unrealized_gl": gl, "unrealized_gl_pct": round(gl / (qty * avg) * 100, 2),
            "final_score": row["final_score"], "action": row["action"],
            "late_leg_penalty": row["late_leg_penalty"], "sector": row["snap"]["sector"],
            "flag": _position_flag(row, gl / (qty * avg) * 100),
        })
    for symbol, desc, pct, last4, acct_type, price in DEMO_ETFS:
        qty = 40
        avg = round(price / (1 + pct / 100), 2)
        value = round(qty * price, 2)
        gl = round(value - qty * avg, 2)
        positions.append({
            "account_last4": last4, "account_type": acct_type, "symbol": symbol, "description": desc,
            "asset_type": "COLLECTIVE_INVESTMENT", "quantity": qty, "average_price": avg, "current_price": price,
            "market_value": value, "unrealized_gl": gl, "unrealized_gl_pct": round(gl / (qty * avg) * 100, 2),
            "flag": None,
        })

    return {
        "scorecard": {"generated_at": GENERATED_AT, "count": len(rows), "rows": rows},
        "residual_momentum": {"generated_at": GENERATED_AT, "ff3_data_through": "202608",
                              "count": len(rm_rows), "rows": rm_rows},
        "portfolio": {"authenticated": True, "positions": positions},
    }


def _script_json(obj) -> str:
    """JSON that is safe inside a <script type="application/json"> block."""
    return json.dumps(obj, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


BLOCK_RE = re.compile(r"<!-- DEMO-DATA-START.*?DEMO-DATA-END -->", re.S)


def main() -> None:
    demo = build()
    block = (
        "<!-- DEMO-DATA-START (generated by backend/make_demo_data.py -- fictional, do not edit by hand) -->\n"
        '<script type="application/json" id="demo-data">' + _script_json(demo) + "</script>\n"
        "<!-- DEMO-DATA-END -->"
    )
    html = TEMPLATE.read_text()
    if not BLOCK_RE.search(html):
        sys.exit(f"{TEMPLATE} has no DEMO-DATA-START/END markers to fill.")
    TEMPLATE.write_text(BLOCK_RE.sub(lambda _: block, html))

    from collections import Counter
    rows = demo["scorecard"]["rows"]
    print(f"wrote demo block: {len(rows)} companies, {demo['residual_momentum']['count']} residual-momentum rows, "
          f"{len(demo['portfolio']['positions'])} positions")
    print("actions:", dict(Counter(r["action"] for r in rows)))


if __name__ == "__main__":
    main()
