"""
Local dev server for the GARP dashboard, adding a live "Refresh Data" button
on top of the static-file workflow in build_dashboard.py.

A plain HTML file can't re-scrape Finviz on its own -- that needs a server-
side process to make the requests. This is a minimal stdlib-only server
(no new dependencies) that serves the dashboard directory as static files
and exposes two endpoints the page's JS calls:

  POST /api/refresh         start a full re-score in a background thread
  GET  /api/refresh/status  poll progress while it runs

Usage:
  source .venv/bin/activate
  python backend/server.py [--port 8765]

Then open http://127.0.0.1:8765 -- the same dashboard, but the Refresh
Data button now works. Opening dashboard/index.html directly via file://
still works too; it just shows the last-generated snapshot with refresh
disabled, since there's no server behind it in that mode.

Before the first build there is no dashboard/index.html yet; the server then
serves dashboard/template.html, which shows the fictional demo dataset until
a refresh replaces it with real scores.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dashboard as bd  # noqa: E402
import schwab_client  # noqa: E402
import residual_momentum as rm  # noqa: E402

_lock = threading.Lock()
_state = {"running": False, "current": 0, "total": 0, "ticker": None, "error": None}

_rm_lock = threading.Lock()
_rm_state = {"running": False, "current": 0, "total": 0, "ticker": None, "error": None}


def _run_residual_momentum() -> None:
    with _rm_lock:
        if _rm_state["running"]:
            return
        _rm_state.update(running=True, current=0, total=0, ticker=None, error=None)

    def on_progress(i: int, total: int, ticker: str) -> None:
        with _rm_lock:
            _rm_state.update(current=i, total=total, ticker=ticker)

    try:
        if not schwab_client.is_authenticated():
            raise RuntimeError("Schwab isn't connected yet (no .schwab_token.json) -- see the README's Schwab integration section")
        rm.run(on_progress=on_progress)
    except Exception as e:
        with _rm_lock:
            _rm_state["error"] = str(e)
    finally:
        with _rm_lock:
            _rm_state["running"] = False


# Heuristic-only, not research-derived: flags a held position when it's
# either matched by the score's own hard override (falling-knife AVOID) or
# crosses a simple, disclosed P&L threshold. Stop-loss/profit-take rule
# efficacy is genuinely mixed in the literature (see
# research/garp-momentum-literature-review.html section 5) -- this exists
# for discipline/visibility, not because these specific numbers are proven.
def _position_flag(row: dict | None, unrealized_pct: float | None) -> dict | None:
    if row is not None and row.get("action") == "AVOID" and "Falling-knife" in row.get("notes", ""):
        return {"kind": "loss_cut", "reason": "Falling-knife filter triggered"}
    if unrealized_pct is not None and unrealized_pct <= -15:
        return {"kind": "loss_cut", "reason": f"Down {abs(unrealized_pct):.0f}% -- check your loss-cutting rule"}
    if row is not None and unrealized_pct is not None:
        penalty = row.get("late_leg_penalty", 0)
        if unrealized_pct >= 40 or (unrealized_pct >= 20 and penalty >= 6):
            return {"kind": "profit_take", "reason": f"Up {unrealized_pct:.0f}% (LateLegPenalty {penalty:.1f}/10) -- check your profit-taking rule"}
    return None


def _build_portfolio() -> dict:
    if not schwab_client.is_authenticated():
        return {"authenticated": False}

    positions = schwab_client.get_positions()

    scorecard_path = bd.DATA_OUTPUT
    by_ticker = {}
    if scorecard_path.exists():
        payload = json.loads(scorecard_path.read_text())
        by_ticker = {r["ticker"]: r for r in payload["rows"]}

    out = []
    for p in positions:
        row = by_ticker.get(p["symbol"])
        entry = dict(p)
        if row is not None:
            entry["final_score"] = row["final_score"]
            entry["action"] = row["action"]
            entry["late_leg_penalty"] = row["late_leg_penalty"]
            entry["sector"] = row["snap"]["sector"]
        entry["flag"] = _position_flag(row, p["unrealized_gl_pct"])
        out.append(entry)

    return {"authenticated": True, "positions": out}


def _run_refresh(limit: int | None) -> None:
    with _lock:
        if _state["running"]:
            return
        _state.update(running=True, current=0, total=0, ticker=None, error=None)

    def on_progress(i: int, total: int, ticker: str) -> None:
        with _lock:
            _state.update(current=i, total=total, ticker=ticker)

    try:
        results = bd.run(limit, on_progress=on_progress)
        bd.write_outputs(results)
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(bd.ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/refresh/status":
            with _lock:
                self._json(200, dict(_state))
            return
        if path == "/api/residual_momentum/status":
            with _rm_lock:
                self._json(200, dict(_rm_state))
            return
        if path == "/api/portfolio":
            try:
                self._json(200, _build_portfolio())
            except Exception as e:
                self._json(500, {"error": str(e)})
            return
        if path in ("", "/"):
            built = bd.DASHBOARD_OUTPUT.exists()
            self.path = "/dashboard/index.html" if built else "/dashboard/template.html"
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/refresh":
            with _lock:
                already = _state["running"]
            if already:
                self._json(409, {"status": "already_running"})
                return
            threading.Thread(target=_run_refresh, args=(None,), daemon=True).start()
            self._json(202, {"status": "started"})
            return
        if path == "/api/residual_momentum/refresh":
            with _rm_lock:
                already = _rm_state["running"]
            if already:
                self._json(409, {"status": "already_running"})
                return
            threading.Thread(target=_run_residual_momentum, daemon=True).start()
            self._json(202, {"status": "started"})
            return
        self.send_error(404)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Serving GARP dashboard at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
