"""
One-off exploration script for the Schwab Market Data + Accounts APIs --
NOT wired into the scoring pipeline. Purpose: find out what's actually in
the response payloads (does Quote.Fields.FUNDAMENTAL include PEG/sector?
what does daily price history look like? what do real positions look
like?) before deciding what, if anything, to build on top of it.

Auth is a two-step manual flow (schwab-py's client_from_received_url),
because the redirect step needs an interactive browser login this script
can't do on its own:

  python backend/schwab_explore.py start
      -> prints an authorization URL. Open it, log into Schwab yourself,
         approve the app. You'll land on an error page at 127.0.0.1 --
         that's expected, nothing is listening on that port. Copy the
         FULL URL from the address bar at that point.

  python backend/schwab_explore.py finish "<the URL you copied>"
      -> exchanges it for a token (saved to .schwab_token.json, gitignored),
         then runs a few read-only exploratory calls and prints the raw
         JSON shapes.

Later runs need no args -- a saved token file authenticates automatically:

  python backend/schwab_explore.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schwab_client  # noqa: E402

ROOT = schwab_client.ROOT
TOKEN_PATH = schwab_client.TOKEN_PATH
CONTEXT_PATH = ROOT / ".schwab_auth_context.json"
load_env = schwab_client.load_env
get_client = schwab_client.get_client


def start():
    import schwab.auth as auth

    load_env()
    api_key = os.environ["SCHWAB_APP_KEY"]
    callback_url = os.environ["SCHWAB_CALLBACK_URL"]

    ctx = auth.get_auth_context(api_key, callback_url)
    CONTEXT_PATH.write_text(json.dumps({
        "callback_url": ctx.callback_url,
        "authorization_url": ctx.authorization_url,
        "state": ctx.state,
    }))

    print("1. Open this URL and log into Schwab yourself:\n")
    print(f"   {ctx.authorization_url}\n")
    print("2. Approve the app. You'll land on a page that fails to load at")
    print("   127.0.0.1 -- that's expected, nothing is running there.")
    print("3. Copy the FULL url from your browser's address bar at that point")
    print("   (it'll start with https://127.0.0.1:3000/api/callback?code=...)")
    print('4. Run: python backend/schwab_explore.py finish "<that url>"')


def finish(received_url: str):
    import schwab.auth as auth

    load_env()
    api_key = os.environ["SCHWAB_APP_KEY"]
    app_secret = os.environ["SCHWAB_APP_SECRET"]

    saved = json.loads(CONTEXT_PATH.read_text())
    ctx = auth.AuthContext(**saved)

    def write_token(token, *args, **kwargs):
        TOKEN_PATH.write_text(json.dumps(token))

    client = auth.client_from_received_url(
        api_key, app_secret, ctx, received_url, write_token,
    )
    CONTEXT_PATH.unlink(missing_ok=True)
    print("Authenticated. Token saved to .schwab_token.json\n")
    explore(client)


def explore(client):
    from schwab.client.base import BaseClient

    print("=" * 70)
    print("QUOTE (AAPL) -- all fields")
    print("=" * 70)
    r = client.get_quote("AAPL", fields=[
        BaseClient.Quote.Fields.QUOTE,
        BaseClient.Quote.Fields.FUNDAMENTAL,
        BaseClient.Quote.Fields.REFERENCE,
    ])
    print(r.status_code)
    print(json.dumps(r.json(), indent=2)[:4000])

    print("\n" + "=" * 70)
    print("DAILY PRICE HISTORY (AAPL) -- last ~1 month, showing 3 bars")
    print("=" * 70)
    r = client.get_price_history_every_day("AAPL")
    print(r.status_code)
    body = r.json()
    if "candles" in body:
        print(f"{len(body['candles'])} candles returned")
        print(json.dumps(body["candles"][:3], indent=2))
    else:
        print(json.dumps(body, indent=2)[:2000])

    print("\n" + "=" * 70)
    print("ACCOUNT NUMBERS")
    print("=" * 70)
    r = client.get_account_numbers()
    print(r.status_code)
    print(json.dumps(r.json(), indent=2))

    print("\n" + "=" * 70)
    print("ACCOUNTS (with positions)")
    print("=" * 70)
    r = client.get_accounts(fields=[BaseClient.Account.Fields.POSITIONS])
    print(r.status_code)
    print(json.dumps(r.json(), indent=2)[:4000])


if __name__ == "__main__":
    if len(sys.argv) == 1:
        explore(get_client())
    elif sys.argv[1] == "start":
        start()
    elif sys.argv[1] == "finish":
        finish(sys.argv[2])
    else:
        print(__doc__)
