"""
Thin, reusable wrapper around schwab-py for the pieces this app needs:
an authenticated client from the saved token, normalized positions across
all linked accounts, and daily price history for the residual-momentum
pipeline. Auth itself (the interactive login) lives in schwab_explore.py --
this module assumes .schwab_token.json already exists.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / ".schwab_token.json"
ENV_PATH = ROOT / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


def is_authenticated() -> bool:
    return TOKEN_PATH.exists()


def get_client():
    import schwab.auth as auth

    load_env()
    api_key = os.environ["SCHWAB_APP_KEY"]
    app_secret = os.environ["SCHWAB_APP_SECRET"]
    return auth.client_from_token_file(str(TOKEN_PATH), api_key, app_secret)


def get_positions() -> list[dict]:
    """Flat list of positions across all linked accounts, normalized."""
    from schwab.client.base import BaseClient

    client = get_client()
    accounts = client.get_accounts(fields=[BaseClient.Account.Fields.POSITIONS]).json()

    out = []
    for acct in accounts:
        sa = acct["securitiesAccount"]
        acct_last4 = sa["accountNumber"][-4:]
        acct_type = sa.get("type", "")

        for p in sa.get("positions", []):
            instrument = p.get("instrument", {})
            long_qty = p.get("longQuantity", 0) or 0
            short_qty = p.get("shortQuantity", 0) or 0
            qty = long_qty - short_qty
            avg_price = p.get("averagePrice")
            market_value = p.get("marketValue")
            current_price = (market_value / qty) if qty else None

            unrealized = p.get("longOpenProfitLoss") if long_qty else p.get("shortOpenProfitLoss")
            cost_basis = (avg_price * qty) if avg_price and qty else None
            unrealized_pct = (unrealized / abs(cost_basis) * 100) if unrealized is not None and cost_basis else None

            out.append({
                "account_last4": acct_last4,
                "account_type": acct_type,
                "symbol": instrument.get("symbol"),
                "description": instrument.get("description"),
                "asset_type": instrument.get("assetType"),
                "quantity": qty,
                "average_price": avg_price,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_gl": unrealized,
                "unrealized_gl_pct": unrealized_pct,
            })
    return out


def get_daily_history(symbol: str) -> Optional[list[dict]]:
    """Full available daily OHLCV history for one symbol, oldest first."""
    client = get_client()
    r = client.get_price_history_every_day(symbol)
    if r.status_code != 200:
        return None
    return r.json().get("candles")
