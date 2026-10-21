# GARP + Momentum Scorecard

Weekly GARP (Growth at a Reasonable Price) + Momentum swing-trading scorecard
for the S&P 500, rendered as a static HTML dashboard.

Built with [Claude Code](https://claude.com/claude-code).

> **Personal research project -- not investment advice.** Nothing here is a
> recommendation to buy or sell anything. The scores are a transparent way to
> organize a screen, not a validated strategy: the backtest in this repo (see
> [Backtest](#backtest-residual-momentum-vs-the-apps-momentum-bucket)) found no
> statistically significant edge for the momentum signals. Market data comes
> from third-party sites; check their terms of use before running the pipeline
> at scale or redistributing anything it returns. No scraped data, credentials
> or account information is stored in this repo.

## Try the dashboard (no setup, no data, no API keys)

`dashboard/template.html` ships with a built-in **demo dataset** -- 63
invented companies across 11 sectors, a residual-momentum column, and a demo
portfolio -- so it fills in and works the moment you open it. Double-click the
file, or:

```bash
open dashboard/template.html        # macOS; any browser works
```

A yellow **DEMO** banner stays on screen the whole time. Every company, ticker
and number is fictional: the *inputs* are made up, but they are scored by the
real model in `backend/scorer.py`, so the buckets, penalties, actions and
missing-data flags behave exactly as they do on live data. Any resemblance to a
real company or ticker is coincidental, and nothing in the demo says anything
about real stocks.

Then see [Using the dashboard](#using-the-dashboard) below for what to click,
including a short guided tour of the demo data.

## Using the dashboard

Three tabs sit under the header: **Scorecard** (every stock, one row each),
**Sectors** (the same data rolled up by sector), and **Portfolio** (your
holdings, scored). Everything is client-side -- sorting, filtering and
expanding rows never leave the page.

### Header

| Element | What it does |
|---|---|
| **Title / meta text** (top right) | Live data: `<N> scored · generated <date>`. Demo: `DEMO · 63 fictional companies`. |
| **⟳ Refresh Data** | Re-scrapes and re-scores the full S&P 500 (about 6-7 minutes), shows live progress in a status bar under the header, then reloads the table in place. Needs the local server -- see [Live refresh](#live-refresh--sectors-tab). |
| **⟳ Refresh Residual Mom.** | Re-runs the residual-momentum regression (about 4-5 minutes). Needs the local server *and* a Schwab connection. |

Opened straight from a file, the refresh buttons just say that they need the
local server -- nothing breaks, and the page keeps showing what it has.

### Scorecard tab

Rows start sorted by **Score**, highest first.

| Column | Meaning |
|---|---|
| **Ticker / Company / Sector** | Identity. |
| **Sector Rank** | `#3/21` = third-best FinalScore among the 21 scored stocks in its sector. Colored green (top of sector) to red (bottom). |
| **Price** | Last price at generation time. |
| **Momentum** | Out of 40: trend vs. the 20/50/200-day averages, RSI zone, closeness to the 52-week high, relative strength vs. SPY. |
| **Valuation** | Out of 25: Forward P/E and PEG. |
| **Quality** | Out of 20: ROIC, ROE, profit margin. |
| **Balance** | Out of 15: debt/equity and current ratio. |
| **Penalty** | 0-10, **subtracted**. How stretched or late the move looks (extension, thin volume, fading week-over-month). Shown as `−4.5`. |
| **Res. Mom.** | Residual momentum -- a *separate* signal that is **not** part of the Score. `—` means there wasn't enough price history to compute it. |
| **Score** | FinalScore, 0-100 = Momentum + Valuation + Quality + Balance − Penalty. |
| **Action** | `BUY/ADD` (≥ 80), `BUY` (65-79), `WATCH` (50-64), `AVOID` (< 50) -- or `AVOID` regardless of score when the falling-knife filter fires. |

**Colors.** Bucket numbers go green → blue → yellow → red by how much of that
bucket's maximum they earned (≥ 75%, ≥ 50%, ≥ 25%, below). Penalty is grey at
0, then white, yellow and red as it grows. Action pills are green (`BUY/ADD`),
blue (`BUY`), yellow (`WATCH`), red (`AVOID`).

**Sort.** Click any column header. Numeric columns sort highest-first on the
first click; Ticker, Company, Sector, Action and Sector Rank sort A→Z / best→worst.
Click the same header again to reverse. The active header turns blue.
Sorting by *Sector Rank* ascending lines up every sector's #1 pick first.

**Search and filter.** The box matches ticker *or* company name as you type.
The **Sector** and **Action** dropdowns narrow the table, and they combine with
each other and with the search box. The counter on the right (`12 shown`) tells
you how many rows survive. Reset a dropdown to `All` to clear it.

**Expand a row.** Click anywhere on a row to open its breakdown directly
underneath; click it again to close it. One row is open at a time.

1. **Summary line** -- `BaseScore − LateLegPenalty = FinalScore`, the action
   note (for example "Falling-knife filter triggered"), and the stock's rank
   within its sector.
2. **Five bars** -- Momentum / Valuation / Quality / Balance, plus the
   Late-Leg Penalty in red, each against its maximum.
3. **Raw inputs** -- the 17 numbers the buckets were scored from (RSI, relative
   volume, distance from the 52-week high, 1-week / 1-month / 1-quarter
   performance, SMA 20/50/200 distance, P/E, Forward P/E, PEG, ROIC, ROE,
   profit margin, debt/equity, current ratio).
4. **Sector-relative** -- Valuation, Quality and Balance re-expressed as a
   percentile among the stock's *sector* peers (`89th pctile`), so a stock is
   judged against its own industry's norms rather than the whole index.
   Momentum is deliberately left out of this comparison (explained in
   [Within-sector ranking](#within-sector-ranking)).
5. **Residual momentum** -- the score, its three factor betas (market, size,
   value) and the date windows used; or a note when there isn't enough history.

**Missing data is shown, never hidden.** If an input couldn't be obtained it
scores **0** on its line item (the model never assumes a "neutral" value), and
the dashboard says so in two places: a yellow **`~ est.`** badge on the affected
bucket's bar (hover it for how many inputs were missing), and the raw input
itself shows `—` in italics with `(missing)`. A `~ est.` score is a floor, not
a measurement -- compare it with that in mind.

### Sectors tab

One row per sector with the average Momentum / Valuation / Quality / Balance /
Penalty and average Score of every stock in it, plus:

- **Stocks** -- how many stocks the averages rest on. A high average over
  three stocks means much less than the same average over thirty.
- **Breadth** -- a stacked bar of how that sector's stocks split across
  `BUY/ADD` (green), `BUY` (blue), `WATCH` (yellow) and `AVOID` (red), with the
  share that is `BUY` or better written underneath. This is what stops one
  large name from carrying an average.

Click a column header to re-sort (Avg Score, highest first, is the default).
**Click a sector's name** to jump to the Scorecard tab already filtered to that
sector; set the Sector dropdown back to `All` there to clear it.

### Portfolio tab

One row per position: account (`…0002 (MARGIN)`), symbol, quantity, average
cost, current price, market value, unrealized gain/loss in dollars and percent,
and -- when the symbol is in the screened universe -- its sector, Score and
Action. Anything outside the screen (ETFs, for example) is shown plainly as
"not in the screen" rather than being given a guessed score.

The **Flag** column is the one thing to read carefully. It is a deliberately
simple, disclosed rule, not a recommendation and not backtested:

| Flag | Fires when |
|---|---|
| **Loss-cut watch** (red) | the falling-knife filter fired on a holding, **or** the position is down 15% or more. |
| **Profit-take watch** (yellow) | the position is up 40% or more, **or** up 20% or more while its Late-Leg Penalty is 6 or higher (a big gain *and* a stretched chart). |

Hover a pill for the specific reason. Note that flags look at your *P&L* and
the falling-knife filter, not at whether the Score is still high -- a holding
can show a loss-cut flag next to a `BUY` action, and that is working as
designed. In the demo, the fictional portfolio loads immediately; with real
data the tab needs the local server and a Schwab connection (see
[Schwab integration](#schwab-integration)).

### A five-minute tour of the demo data

Open `dashboard/template.html` and try these in order. (The tour describes the
shipped demo seed; if you regenerate the demo data with a different seed, the
names below will change.)

1. **The leaderboard.** The table opens sorted by Score. **Ledgerton Asset
   Management (`LDGR`)** is #1 at **86.0 / BUY/ADD**. Click its row to see why:
   Momentum 38/40, Quality 20/20, no penalty. Click the row again to close it.
2. **A strong trend that is "late".** Click the **Penalty** header.
   **Pixelrow Interactive (`PXLR`)** sits on top at **−10.0**, the maximum.
   Its Momentum is 35/40, but RSI is 71.5 on lighter-than-normal volume and the
   last week turned negative after a strong month -- so it lands at 56.0 /
   `WATCH` instead of `BUY`. Expand the row and look at the red penalty bar.
3. **The override.** Set **Action** to `AVOID` and open **Autovale Motors
   (`AUTV`)**. Its Score is **55.0** -- a `WATCH` on numbers alone, with
   Valuation at 25/25 -- but it shows `AVOID`, and the summary line says
   "Falling-knife filter triggered": the price is below both its 50- and
   200-day averages with RSI under 40. Its Momentum is 0/40 (it is also 41%
   under its 52-week high), and the hard rule overrides the composite.
4. **Missing data.** Clear the filters and search `ZNTH`. **Zenthra Security**
   shows `~ est.` on Momentum: it listed recently, so it has no 200-day average
   yet, which is flagged `(missing)` in the raw inputs and scored 0. Its
   `Res. Mom.` is `—` for a related reason (less than 36 months of history).
   Then search `MRKT` -- Marketstone Exchange is a `BUY/ADD` whose **Balance**
   is `~ est.` because Debt/Equity is missing.
5. **Within a sector.** Clear the search, set **Sector** to `Technology`.
   Ten stocks, ranked `#1/10` (Helixnet Semiconductor, `HLNX`) down to `#10/10`.
   Expand any of them and look at the **Sector-relative** percentiles.
   Then set Sector back to `All` and click **Sector Rank** to line up every
   sector's #1 pick.
6. **When the two momentum signals disagree.** Click the **Res. Mom.** header
   (highest first). Near the top, **Pinnacrest Financial (`PNCL`)** is an
   `AVOID` at 47.0 yet has a residual momentum of **+0.53**: it has been
   outperforming what its market/size/value exposure predicts, even though the
   composite doesn't like it. Near the bottom, **Homestead Furnishings
   (`HMST`)** is the reverse -- a `BUY` at 79.0 with **−0.48**, meaning its
   recent run is mostly explained by factor exposure rather than anything
   stock-specific. The column is kept separate from the Score so you can see
   disagreements like these; the
   [backtest](#backtest-residual-momentum-vs-the-apps-momentum-bucket) explains
   why it isn't blended in.
7. **Sectors.** Open the **Sectors** tab. *Basic Materials* has the highest
   average (67.8) -- over only **3** stocks (see the Stocks column), while
   *Technology* is 66.5 over 10. *Real Estate* is the weakest at 36.8, and
   *Utilities* and *Communication Services* have no `BUY` or better at all.
   Click **Utilities** to land on the Scorecard filtered to its four names.
8. **Portfolio.** Open the **Portfolio** tab: ten fictional positions, four
   flags. `NVLK` is up 58% (profit-take, ≥ 40%). `PXLR` is only up 27% but
   flagged because its penalty is 10/10 (the "gain *and* stretched" rule),
   whereas `QRTZ` is up 24% with a penalty of 2.0 and is left alone. `GNMX`
   trips the falling-knife filter, and `HRBR` is down 17% -- flagged for
   loss-cut even though the model still scores it `BUY` at 77.0. The three
   `DM…` funds are unscored because they aren't in the screen.
9. **Refresh.** Click **⟳ Refresh Data**. Opened from a file, it explains that
   live refresh needs the local server. (With `python backend/server.py`
   running, the same click scores the real S&P 500 and replaces the demo.)

### How the demo works

- `dashboard/template.html` is both the page *and* the build template. It
  reads two embedded JSON blocks that `build_dashboard.py` fills in. In the raw
  template those blocks contain a placeholder instead of JSON, so the page
  falls back to the bundled `demo-data` block.
- `python backend/make_demo_data.py` regenerates that block (seeded and
  deterministic; it runs invented inputs through `scorer.score_snapshot`).
- `python backend/build_dashboard.py` writes `dashboard/index.html` with real
  data and **strips the demo block** -- a real dashboard never mixes in
  fictional rows, and the DEMO banner doesn't appear.
- `python backend/server.py` before any build also serves the demo template, so
  a fresh clone isn't a 404; its refresh button then builds the real thing.

## Scoring model

0-100 composite, ranked by `FinalScore = BaseScore - LateLegPenalty`:

- **Momentum/Trend (40 pts)** - SMA200/50/20 alignment, RSI(14) zone, 52-week-high proximity, relative strength vs. SPY (month + quarter)
- **Valuation (25 pts)** - Forward P/E and PEG vs. fixed bands
- **Quality (20 pts)** - ROIC, ROE, Profit Margin vs. fixed bands
- **Balance sheet (15 pts)** - Debt/Equity and Current Ratio (solvency only -- profitability lives in Quality)
- **LateLegPenalty (0-10 pts, subtracted)** - RSI/SMA stretch, relative-volume participation, week-vs-month deceleration
- **Falling-knife filter** - hard AVOID override when price is below SMA50 and SMA200 with RSI < 40

Missing inputs score 0 on their line item (never an assumed "neutral" value)
and are recorded per-ticker so the dashboard can flag a bucket as partly
estimated rather than presenting a gap-filled score identically to a fully
measured one.

Action bands (on FinalScore): ≥80 BUY/ADD, 65-79 BUY, 50-64 WATCH, <50 AVOID.

Data source is Finviz quote-page scraping (no API key required), plus one
SPY fetch per run as the relative-strength benchmark. See
`research/garp-momentum-literature-review.html` for the literature behind
this model and the gap analysis that drove the Quality bucket, the 52-week-high
signal, and the missing-data handling above.

## Usage

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python backend/build_dashboard.py        # full S&P 500 (~6-7 min)
python backend/build_dashboard.py --limit 20   # quick test run
python backend/build_dashboard.py --rerender   # re-render dashboard/index.html
                                                # from existing data/scorecard.json,
                                                # e.g. after a template-only change
```

This writes `data/scorecard.json` and `dashboard/index.html`. Open
`dashboard/index.html` directly in a browser -- the scored data is embedded
inline, so no server is needed. Sort columns by clicking headers, filter by
sector/action/search, and click a row to expand its Momentum/Valuation/
Quality/Balance/LateLegPenalty breakdown. A bucket with a "~ est." badge had
at least one missing input scored as 0 rather than assumed -- hover it for
which fields.

### Live refresh + Sectors tab

Opened directly as a file, the dashboard is a snapshot from the last run --
a plain HTML file can't re-scrape Finviz on its own. To refresh from inside
the browser, run the local server instead:

```bash
python backend/server.py        # http://127.0.0.1:8765
```

Same dashboard, plus a working **Refresh Data** button: it kicks off a full
re-score in a background thread, polls progress live, and reloads the table
in place when done -- no terminal round-trip needed. Opening
`dashboard/index.html` via `file://` still works exactly as before; the
button just shows a message pointing at the server instead of failing
silently.

The **Sectors** tab rolls up the same components (Momentum/Valuation/
Quality/Balance/Penalty/Score) averaged across every scored stock in each
sector, plus a breadth bar (% BUY/BUY-ADD vs. WATCH vs. AVOID) so a strong
average isn't hiding a single large-cap dragging the number up. It's a pure
client-side aggregation of the same per-stock data, not a separate scoring
pass. Click a sector name to jump to the Scorecard tab filtered to it.
Industry-level momentum has its own documented edge on top of individual
stock-picking (Moskowitz & Grinblatt, 1999) -- see
`research/garp-momentum-literature-review.html`. Note this rollup's own
component averages still use the same absolute thresholds as the main
model, so structurally low-growth sectors like Utilities will show lower
Momentum/Quality averages by construction, not necessarily because those
are worse companies.

### Within-sector ranking

The sector-relative gap above is now closed for Valuation, Quality, and
Balance -- but deliberately *not* for Momentum, and that split is load-bearing,
not an oversight:

- Every row shows a **Sector Rank** column (`#3/21`) -- where a stock lands
  among its sector peers by overall FinalScore. Click a header to sort by it;
  sorting ascending groups each sector's #1 pick together.
- The expanded row detail adds a **sector-relative** section: Valuation,
  Quality, and Balance are re-scored as a z-score against sector mean/stdev
  for each underlying metric (PEG, Fwd P/E, ROIC, ROE, Profit Margin,
  Debt/Eq, Current Ratio), then converted to a percentile within the sector.
  This is real differentiation the absolute bands were hiding: as of the run
  this was written against, 52% of Energy and 42% of Financial Services
  stocks were tied at the max 25/25 Valuation score under the absolute
  bands, despite PEG ratios spanning 0.27-3.94 inside Energy alone.
- **Momentum is intentionally excluded** from the sector-relative treatment.
  Valuation/Quality/Balance vary by sector for structural reasons (capital
  intensity, business model, leverage norms), so normalizing them against
  sector peers is well-established practice. Momentum is a different kind of
  signal: Moskowitz & Grinblatt (1999) tested exactly this move -- naively
  adjusting individual stock momentum for industry effects -- and found the
  result "significantly weaker, and for the most part, statistically
  insignificant." A more sophisticated version -- regression-based residual
  momentum -- does show a real, stronger signal (Blitz, Huij & Martens,
  2011); that one needed historical daily-return time series Finviz can't
  provide, which is what the Residual Momentum section below is. See
  `research/garp-momentum-literature-review.html` §6 for the full writeup.

Re-run `build_dashboard.py` (e.g. weekly), or use the Refresh Data button
in server mode. Sector rank and sector-relative percentiles are computed
client-side from the same per-stock data already in `scorecard.json` --
no re-scrape needed after a template-only change like this one.

## Schwab integration

Two more features run on top of a connected Schwab developer account
(`developer.schwab.com`), used read-only for market data and your own
account positions -- never for placing trades.

**One-time setup:**
```bash
pip install schwab-py
# .env (gitignored) with SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL
# matching your app's registered redirect URI on developer.schwab.com

python backend/schwab_explore.py start
# open the printed URL, log into Schwab yourself, approve the app --
# you'll land on a 127.0.0.1 URL that fails to load, which is expected
python backend/schwab_explore.py finish "<the URL you landed on>"
# exchanges the code for a token, saved to .schwab_token.json (gitignored)
```
The authorization code is short-lived (well under a minute) -- run `finish`
immediately after `start`, don't let it sit. The token refreshes itself
automatically after that; re-run the `start`/`finish` pair only if
`.schwab_token.json` is deleted or the refresh token itself expires (Schwab
caps refresh tokens at 7 days server-side, independent of anything this app
does).

### Portfolio positions and flags

Server mode only (needs a live Schwab session). Pulls real positions across
every linked account -- quantity, average cost, market value, unrealized
gain/loss -- and cross-references each one against its current score/action
where the symbol is in the S&P 500 screen (ETFs and anything outside the
screened universe show plainly as "not in S&P 500 screen" rather than a
guessed score). A **Flag** column calls out two cases: the falling-knife
filter has triggered on a held name, or a simple, disclosed P&L threshold
is crossed (default: -15% loss, or +20-40% gain depending on how stretched
LateLegPenalty is). These thresholds are a starting point for visibility,
not a backtested rule -- stop-loss/profit-take efficacy is genuinely mixed
in the literature (see the research memo, section 5). This is the position-
tracking piece flagged as the biggest gap since the very first research
pass: the app previously could only say what to buy, never whether to keep
holding something.

### Residual momentum

A second, complementary signal to the main Momentum bucket, not folded into
FinalScore -- shown as its own **Res. Mom.** column and a diagnostic
section in the row detail. Methodology (Blitz, Huij & Martens, 2011):

1. For each stock, regress its trailing 36 *monthly* returns (minus the
   risk-free rate) on the Fama-French 3 factors (Mkt-RF, SMB, HML) via OLS.
2. Take the residuals -- actual return minus what the stock's own
   market/size/value beta would predict -- from the most recent 12 of
   those 36 months, skipping the single most recent month (the standard
   momentum skip-month, avoiding short-term reversal contamination).
3. Score = mean of those 12 residuals / their own standard deviation -- a
   t-stat-like measure that rewards *consistent* outperformance of a
   stock's factor-implied return, not one big month.

Two data sources make this possible that weren't available before: Fama-
French factors from Kenneth French's public Data Library (free, cached
locally, refreshed monthly with a ~1-2 month natural lag), and daily price
history from Schwab's Market Data API (`get_price_history_every_day`),
resampled to monthly closes. Schwab's price history is a **price** return,
not total return -- dividends aren't added back in, a disclosed
simplification versus the original paper's construction, not an attempt at
an exact reproduction.

```bash
python backend/residual_momentum.py             # full S&P 500 (~4-5 min)
python backend/residual_momentum.py --limit 20   # quick test run
```

In server mode, the **Refresh Residual Mom.** button runs this the same
way the main Refresh Data button runs the Finviz scrape -- background
thread, live progress, in-place reload. A handful of tickers (recent
IPOs/spinoffs without 36 months of trading history -- GEV, SOLV, VLTO,
RDDT, TKO at last count) show "--" since the regression has nothing to fit.

### Backtest (residual momentum vs. the app's Momentum bucket)

```bash
python backend/backtest_residual_momentum.py fetch   # pull full price history, cache month-end features (~5 min)
python backend/backtest_residual_momentum.py run     # run the tests off the cache (~1 min)
```

Rebuilds each price-based signal point-in-time at every month-end since 2008
and scores it against the next month's return (equal-weighted quintiles,
Fama-MacBeth cross-sections). Only price-derived signals can be tested --
Valuation/Quality/Balance need point-in-time fundamentals this app doesn't
have. It rebuilds the live residual-momentum scores to within 2.4e-6, so it
tests the real signal. **Result (Oct 2026, 2008-2026, ~435 stocks/month):
nothing is statistically significant** -- residual momentum's top-minus-bottom
quintile spread is +0.07%/mo at ideal timing (t = 0.3) and +0.18%/mo as used
live with the factor-data lag (t = 0.9); the app's Momentum bucket is -0.25 and
-0.43%/mo (t = -0.9, -1.6), i.e. no edge and leaning the wrong way; adding the
+/-4 tilt changes the bucket's spread by -0.03%/mo (t = -1.2). Residual
momentum's one visible plus is crash behavior: worst month -15% to -18% vs.
-34% to -38% for plain 12-1 momentum (April 2009). Caveats that bias the test
*against* momentum: the universe is today's S&P 500 (survivorship -- beaten-down
names that recovered are overrepresented), and even plain 12-1 momentum shows
nothing here (-0.07%/mo, t = -0.2), so the test can't confirm the academic
premium either. Treat it as "no support for baking this into FinalScore," not
as proof residual momentum doesn't work.

Data note: Schwab's price history is split-adjusted but also has large
*special* dividends subtracted from old prices (regular dividends are not),
which turns some series negative (COST, TDG, PCAR, CME, EOG, EVRG, KDP, TPL,
ACGL). The backtest drops those nine; the live 36-month window for them stays
positive, so their dashboard scores are usable, just slightly skewed.

One ticker-format note if either full pipeline (`build_dashboard.py` or
`residual_momentum.py`) is being modified: share-class tickers need a
different separator per data source -- Wikipedia/Schwab use a dot
(`BRK.B`), Finviz wants a dash (`BRK-B`), Schwab's price-history endpoint
specifically wants a slash (`BRK/B`). The canonical ticker stored
everywhere in this app's own data is the dot form; each fetch function
converts to what its own source needs right before the request.
