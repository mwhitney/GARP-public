"""
Pull S&P 500 constituents, score them with the GARP+Momentum model, and
render a static dashboard (dashboard/index.html) with the results embedded
inline as JSON -- no server or fetch() required, just open the file.

Usage:
  source .venv/bin/activate
  python backend/build_dashboard.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scorer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_TEMPLATE = ROOT / "dashboard" / "template.html"
DASHBOARD_OUTPUT = ROOT / "dashboard" / "index.html"
DATA_OUTPUT = ROOT / "data" / "scorecard.json"
RESIDUAL_MOMENTUM_PATH = ROOT / "data" / "residual_momentum.json"

# The raw template carries a fictional demo dataset (see make_demo_data.py) so
# it is browsable on its own. Real dashboards drop that block.
DEMO_BLOCK_RE = re.compile(r"<!-- DEMO-DATA-START.*?DEMO-DATA-END -->\n?", re.S)


def _script_json(obj) -> str:
    """JSON that is safe to embed inside a <script type="application/json"> block."""
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def run(limit: int | None = None, on_progress=None) -> list[dict]:
    tickers = scorer.load_sp500_tickers()
    if limit:
        tickers = tickers[:limit]

    print("Fetching SPY (relative-strength benchmark)...")
    spy = scorer.fetch_finviz_snapshot("SPY")
    if spy is None:
        print("Warning: SPY fetch failed -- relative-strength component will score 0 for every ticker this run.")

    results = []
    skipped = []

    for i, t in enumerate(tickers, 1):
        ft = scorer.normalize_for_finviz(t)
        if ft is None:
            skipped.append(t)
            continue

        snap = scorer.fetch_finviz_snapshot(ft)
        if snap is None:
            skipped.append(t)
            continue
        snap.ticker = t  # keep the canonical dot-form ticker (BRK.B), not Finviz's dash-form fetch key

        scored = scorer.score_snapshot(snap, spy=spy)
        results.append(scored.to_dict())
        print(f"[{i}/{len(tickers)}] {t}: final={scored.final_score:.1f} action={scored.action}")
        if on_progress:
            on_progress(i, len(tickers), t)

    if skipped:
        print(f"\nSkipped {len(skipped)} tickers (no data / special case): {', '.join(skipped)}")

    results.sort(key=lambda r: r["final_score"], reverse=True)
    return results


def write_outputs(results: list[dict], generated_at: str | None = None) -> None:
    from datetime import datetime, timezone

    payload = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "rows": results,
    }

    DATA_OUTPUT.parent.mkdir(exist_ok=True)
    DATA_OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {DATA_OUTPUT}")

    if RESIDUAL_MOMENTUM_PATH.exists():
        rm_payload = json.loads(RESIDUAL_MOMENTUM_PATH.read_text())
    else:
        rm_payload = {"generated_at": None, "ff3_data_through": None, "count": 0, "rows": []}

    template = DEMO_BLOCK_RE.sub("", DASHBOARD_TEMPLATE.read_text())
    html = template.replace("__SCORECARD_DATA__", _script_json(payload))
    html = html.replace("__RESIDUAL_MOMENTUM_DATA__", _script_json(rm_payload))
    DASHBOARD_OUTPUT.write_text(html)
    print(f"Wrote {DASHBOARD_OUTPUT}")


def rerender() -> None:
    """Re-render dashboard/index.html from the existing scorecard.json --
    for template/UI-only changes that don't need a fresh Finviz scrape.
    Preserves the original generated_at rather than overstating freshness."""
    payload = json.loads(DATA_OUTPUT.read_text())
    write_outputs(payload["rows"], generated_at=payload["generated_at"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only score the first N tickers (for quick testing)")
    parser.add_argument("--rerender", action="store_true", help="Re-render the dashboard from existing data/scorecard.json without re-scraping")
    args = parser.parse_args()

    if args.rerender:
        rerender()
        return

    results = run(args.limit)
    write_outputs(results)


if __name__ == "__main__":
    main()
