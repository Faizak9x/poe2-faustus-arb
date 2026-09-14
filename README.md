# PoE 2 Faustus Currency Exchange Arbitrage Detector

*This product isn't affiliated with or endorsed by Grinding Gear Games in any way.*

**Live dashboard: https://faizak9x.github.io/poe2-faustus-arb/** - always-current view of what the hourly check is finding, no GitHub login needed. Updates itself every few minutes.

Detects triangular arbitrage opportunities on Path of Exile 2's in-game Currency
Exchange (Faustus), using only GGG's own public data. It **only detects and
alerts** - it never touches the game. You review every alert and execute
trades yourself, by hand, in the in-game Currency Exchange panel.

---

## Step 1 - Data access: confirmed genuinely public, no OAuth app needed

I checked GGG's [developer docs](https://www.pathofexile.com/developer/docs)
directly. The relevant facts, quoted verbatim:

- From the [authorization docs](https://www.pathofexile.com/developer/docs/authorization),
  describing the `service:cxapi` OAuth scope: *"for access to the Currency
  Exchange API. Note that this API can also be accessed publicly."*
- From the [API reference](https://www.pathofexile.com/developer/docs/reference):
  the Currency Exchange endpoint is listed as a **Public API** with no OAuth
  scope requirement at all.
- I then called the live endpoint directly with no credentials of any kind
  and got real trade data back, confirming this in practice, not just on paper.

**Conclusion: no registered/approved OAuth application is required.** The
poe.ninja fallback mentioned in the brief is not needed. This tool talks
directly to GGG:

```
GET https://web.poecdn.com/api/currency-exchange/<realm>/<id>
```

- `realm`: `poe2` for PC (also supports `xbox`, `sony`)
- `id`: a unix timestamp truncated to the hour. The response gives you
  `next_change_id` to use as `id` on your next call, so you step forward
  one hour at a time. **There is no way to fetch the still-open current
  hour** - only already-closed hourly digests. If `next_change_id` comes
  back equal to the `id` you asked for, that hour hasn't closed yet; the
  tool just logs that and exits cleanly, no error.
- Data covers **all leagues at once** - the response includes a `league`
  field per market, which we filter down to your configured league.

One real GGG requirement that **does** apply even to this public endpoint:
every request must send an identifying `User-Agent` header in the form
`OAuth {name}/{version} (contact: {email})`. This tool does that
automatically using the `CONTACT_EMAIL` you provide - see Setup below. No
actual OAuth handshake happens; this is just the identification format GGG
asks all API consumers to use.

---

## Step 2 - Currency scope: fully dynamic

Nothing is hardcoded. Every run:

1. Fetches whatever pairs GGG reports as traded in the most recently closed
   hour, across whichever currencies were actually active.
2. Computes a **self-scaling volume floor for that specific hour** (see
   below) and filters out any pair where either side traded below it -
   this removes dead/illiquid pairs before they ever reach the arbitrage
   graph.
3. Builds the graph fresh from what's left. Add a new currency to the game
   next patch, and it's automatically included the next time it trades
   above the volume floor - no code changes needed.

**Why a *fixed* volume number doesn't work (found by testing on live data,
not theorized):** I first tried a flat floor of 20 units. On a quieter
league (Standard) that fully eliminated the noise. But on the actual
current **Forbidden Rites** league - much higher real trading activity -
that same flat floor of 20 still let through "cycles" claiming 1,968% and
7,460% profit. Those aren't real opportunities; they're single-trade
outliers on pairs that only look "liquid" at 20 units because everything
else in that league trades in the thousands. A number that's a sensible
floor for one league/hour is meaningless noise-filtering for a busier one.

**The fix:** the floor is computed fresh every hour from that hour's own
data - take the smaller side's volume for every pair traded that hour, and
require a pair to be at/above the `MIN_VOLUME_PERCENTILE`-th percentile of
that distribution (default 0.90 = only the busiest 10% of pairs qualify),
with `MIN_VOLUME_ABS_FLOOR` (default 20) as a hard minimum for quiet hours.
Re-tested on the same real Forbidden Rites hour: this computed a floor of
**594 units** automatically and it eliminated every false cycle - 0 left,
down from 10. This adapts on its own as the league gets busier or quieter
over its lifetime, instead of a number I'd have to keep manually re-tuning.

---

## Step 3 - Core algorithm: negative-cycle detection via Bellman-Ford

- Each currency is a graph node. Each traded pair contributes two directed
  edges (A->B and B->A), weighted `-log(rate)`.
- **Rate direction** comes straight from the API's own `lowest_ratio` /
  `highest_ratio` fields, which are keyed by currency id - so there's no
  ambiguity about which currency is "first". Because a hover digest gives a
  *range* of rates (cheapest and priciest trade that hour), each directional
  edge conservatively uses the **worse** of the two implied rates. This
  approximates Faustus's real spread using only historical aggregate data
  (there's no live order book in this API).
- Bellman-Ford runs from an implicit zero-weight source connected to every
  node. A negative-weight cycle = a sequence of trades that returns more
  than you started with = an arbitrage loop. This correctly finds cycles of
  *any* length, not just 3 hops (the classic "triangular" case is just the
  most common one).
- After finding one cycle, its edges are removed and the search repeats (up
  to `MAX_CYCLES_PER_RUN`, default 8), so multiple independent
  opportunities in the same hour can all be reported.
- **I verified this against a synthetic case with a known 20% arbitrage
  (rates 2x, 2x, 0.3x) and it was detected correctly**, then re-verified the
  full pipeline against live real PoE2 Standard-league data pulled directly
  from GGG's endpoint (424 real trade edges, 187 real currencies) with no
  crashes and sane output.

**Persistence check (as requested):** a cycle is only escalated to an alert
after it appears as a qualifying candidate in `PERSISTENCE_HOURS`
*consecutive* hourly pulls (default 2; you can raise it to 3). If an hour is
skipped or the cycle disappears even once, its streak resets - this avoids
acting on single-hour noise in what is, after all, hourly aggregate data,
not live ticks.

---

## Step 4 - Profit threshold

Each candidate cycle's profit is `(product of all leg rates - 1) * 100`,
using the conservative (worst-case) rate on every leg - this already bakes
in an approximation of Faustus's spread, since we deliberately never use
the optimistic end of the hourly rate range. On top of that, a cycle only
becomes a candidate at all if this conservative profit clears
`MIN_PROFIT_PCT` (default **2.0%**, configurable). Combined with the
2-3 hour persistence check, this keeps marginal/rounding-level cycles out
of your alerts.

---

## Step 5 - Output

Every alert (console log, `state/alerts.log` as JSON lines, and optionally
push/Discord) includes:

```
Exalted Orb -> Chaos Orb -> Divine Orb -> Exalted Orb
Expected profit: 3.42%
Confirmed over 2 consecutive hourly pulls
Min leg volume this hour: 84
As of: 2026-09-14T15:05:03Z
League: Forbidden Rites
Execute manually in the in-game Currency Exchange panel.
```

You then go execute those trades yourself in Faustus. The tool never
alerts again for the *same* cycle while it keeps persisting (to avoid
spamming you every hour) - it only pings again if the cycle disappears and
later reappears fresh.

**A note on currency names:** GGG's API only gives internal ids like
`Metadata/Items/Currency/CurrencyModValues`, not display names like
"Exalted Orb". There's no reliable public mapping for this that stays
current league-to-league, so I did **not** hardcode a guessed table (a
wrong guess in a tool used for real trades is worse than an honest raw
name). The tool auto-"humanizes" ids reasonably (strips prefixes, splits
CamelCase) and lets you add your own precise overrides - see
[Currency names](#currency-names) below.

---

## Compliance notes (GGG ToS)

- **Read-only, alerts only.** This tool never sends input to the game and
  never automates any in-game action - it just tells you, in a log/notification,
  what to consider doing yourself. That keeps it outside GGG's macro/automation
  rules entirely, which govern automating keystrokes/game inputs, not reading
  public aggregate market data.
- **Required attribution** is included at the top of this README per GGG's
  request: *"This product isn't affiliated with or endorsed by Grinding Gear
  Games in any way."* Keep this notice if you share the tool further.
- **Required identification header** (`User-Agent: OAuth {name}/{version}
  (contact: {email})`) is sent on every request, using your own contact
  email from config - never hardcoded to anyone else's.
- **Rate limits**: GGG's docs say limits are dynamic and can change; this
  tool only calls the endpoint once per hour, and backs off automatically
  on HTTP 429/503 using the `Retry-After` header, so it stays well within
  any reasonable limit.
- Only the documented public endpoint is used - nothing is reverse-engineered.

---

## Project layout

```
poe2-faustus-arb/
|-- src/
|   |-- config.py       # env var / .env loading
|   |-- ggg_client.py   # calls GGG's public Currency Exchange endpoint
|   |-- graph.py        # rate graph + Bellman-Ford negative-cycle detection
|   |-- names.py        # id -> display name humanizer + optional overrides
|   |-- state.py        # tiny JSON state store (history + persistence streaks)
|   |-- notify.py       # console/log + optional ntfy.sh / Discord alerts
|   `-- main.py         # one hourly run, start to finish
|-- discover_currencies.py   # prints raw ids trading now, for naming them
|-- .github/workflows/hourly.yml   # free hourly automation (see Step 6)
|-- state/               # history.json, alerts.log (committed by the workflow)
|-- .env.example          # copy to .env for local runs
`-- currency_names.json   # optional, you create this (id -> friendly name)
```

---

## Quick start (running it yourself, once)

You'll need Python 3.10+ installed. This machine didn't have Python
installed when this project was built (locked-down Windows edition
blocked automated installs), so if you're on the same PC, install it
yourself from **[python.org/downloads](https://www.python.org/downloads/)**
(check "Add python.exe to PATH" during setup), then:

```bash
cd path\to\poe2-faustus-arb
pip install -r requirements.txt
copy .env.example .env
```

Open `.env` in Notepad and fill in `CONTACT_EMAIL` with your own email
(required by GGG). Then run one check:

```bash
python -m src.main
```

The first run bootstraps from the most recently closed hour and won't have
2 hours of history yet, so it likely won't alert on the very first run even
if something is brewing - that's expected, run it again next hour (or just
set up the automation below, which does this for you forever).

---

## Step 6 - Running it continuously, for free, with no server of your own

You said you're not a developer - here's the whole path in plain steps. It
uses **GitHub Actions**, which runs your code on GitHub's own computers on a
schedule, for free, so nothing needs to stay running on your PC.

### 6.1 Create a GitHub account

1. Go to **[github.com/signup](https://github.com/signup)**.
2. Enter an email, password, and username; verify your email when prompted.
3. Free plan is all you need.

### 6.2 Create a new repository

1. Once logged in, click the **+** in the top-right -> **New repository**.
2. Name it something like `poe2-faustus-arb`.
3. Set it to **Private** (recommended - keeps it visible to only you).
4. Leave everything else default, click **Create repository**.

### 6.3 Upload this project - no command line needed

1. On your new repo's page, click **"uploading an existing file"** (or
   **Add file -> Upload files**).
2. Open this folder on your PC and drag in everything **except** the
   `.env` file and the `state` folder's contents if any exist (the
   `.gitignore` already excludes `.env` from being tracked, but the web
   uploader doesn't read `.gitignore` - just don't drag `.env` in manually).
   Drag in: `src/`, `.github/`, `discover_currencies.py`,
   `requirements.txt`, `.env.example`, `.gitignore`, `README.md`, and the
   `state` folder (with just `.gitkeep` inside).
3. Most browsers let you drag whole folders and GitHub preserves the
   folder structure (`src/main.py`, `.github/workflows/hourly.yml`, etc.) -
   double check after upload that the folder structure looks right.
4. Scroll down, click **Commit changes**.

### 6.4 Add your settings as repo Secrets and Variables

Go to your repo -> **Settings** tab -> **Secrets and variables** -> **Actions**.

**Secrets** tab -> **New repository secret** - add these (values stay
encrypted, never shown again):
| Name | Value |
|---|---|
| `CONTACT_EMAIL` | your own email address |
| `NTFY_TOPIC` | *(optional, see 6.6)* |
| `DISCORD_WEBHOOK_URL` | *(optional, see 6.6)* |

**Variables** tab -> **New repository variable** - add these (plain, visible,
fine for non-secret settings):
| Name | Value |
|---|---|
| `LEAGUE_NAME` | `Forbidden Rites` |
| `REALM` | `poe2` |
| `MIN_VOLUME_PERCENTILE` | `0.90` |
| `MIN_VOLUME_ABS_FLOOR` | `20` |
| `MIN_PROFIT_PCT` | `2.0` |
| `PERSISTENCE_HOURS` | `2` |
| `MAX_CYCLES_PER_RUN` | `8` |
| `APP_NAME` | `poe2-faustus-arb` |

### 6.5 Turn it on and test it

1. Go to the **Actions** tab. If prompted, click **"I understand my
   workflows, go ahead and enable them"**.
2. Click **"Faustus Arbitrage Hourly Check"** in the left list.
3. Click **Run workflow** (top right) -> **Run workflow** again to confirm.
   This runs it immediately instead of waiting for the next hour.
4. After ~30-60 seconds, click into the run to see its log - you should
   see it fetch data and print a summary line. Any problems (like a typo
   in `LEAGUE_NAME`) will show here in plain text.
5. From now on, it runs automatically every hour (at :05 past) forever,
   with no further action from you. Each run updates `state/` in your repo
   so it remembers what it saw last hour.

### 6.6 Get alerted on your phone (optional but recommended)

Since GitHub Actions runs in the cloud, you won't see alerts unless you
check the Actions log yourself - **ntfy.sh** gives free push notifications
with zero signup:

1. Install the **ntfy** app (search "ntfy" on iOS App Store / Google Play).
2. Open it, tap **+** (subscribe to topic), and type a unique, hard-to-guess
   name, e.g. `faiz-poe2-arb-9f3k` (anyone who knows this exact name could
   see your alerts too, so don't make it something guessable like `poe2arb`).
3. Go back to your GitHub repo -> Settings -> Secrets -> add `NTFY_TOPIC` with
   that exact same name.
4. That's it - the next alert the tool finds will pop up on your phone.

*(Prefer Discord? Create a webhook in your Discord server's channel
settings -> Integrations -> Webhooks -> New Webhook -> Copy URL, then set that
as the `DISCORD_WEBHOOK_URL` secret instead/as well.)*

### 6.7 Where to check in on it later

- **Actions tab** -> run history, logs, manual re-runs.
- **`state/alerts.log`** in your repo -> every alert ever fired, as one JSON
  line each.
- **`state/history.json`** -> the last few hours it's seen, useful for
  sanity-checking what it's finding even below the alert threshold.

---

## Currency names

Run this locally (needs Python + your `.env` set up) once the league you
care about has active trades:

```bash
python discover_currencies.py
```

It prints every raw currency id trading that hour, sorted by volume, with
its auto-humanized guess. Create `currency_names.json` in the project root
to override any of them with the exact in-game name, e.g.:

```json
{
  "Metadata/Items/Currency/CurrencyModValues": "Exalted Orb",
  "Metadata/Items/Currency/CurrencyRerollRare": "Chaos Orb"
}
```

This only affects display text in alerts - it has no effect on the
arbitrage math, which always operates on the raw ids.

**Where these names actually came from:** I didn't guess most of these.
poe.ninja's own PoE2 pages render an icon for every currency, and those
icon URLs point at GGG's public art CDN (`web.poecdn.com/gen/image/...`)
with the internal item path base64-encoded right into the URL - e.g. the
icon for "Exalted Orb" decodes to `.../CurrencyAddModToRare.png`, which is
the exact same id this API uses. Cross-referencing poe.ninja's displayed
name against that decoded filename gives an authoritative id -> name
mapping for free, no datamining or game files needed. To add more:
1. Open the matching category on poe.ninja (e.g. `poe.ninja/poe2/economy/<league-slug>/currency`,
   or `/omens`, `/verisium`, etc. for the sidebar categories).
2. In the browser console: grab every `<img alt>` and decode its `src`'s
   base64 segment (`atob()`) to a JSON object with an `f` field - that
   field's filename is the id, `alt` is the confirmed real name.
3. Add `"Metadata/Items/Currency/<Id>": "<Real Name>"` to `currency_names.json`.

A caveat found doing this: don't assume a functionally-similar PoE1 name
carries over - two of my initial guesses (`CurrencyRemoveMod` as "Orb of
Annulment", `CurrencyCorrupt` as "Vaal Orb") turned out to be wrong; PoE2
has separate ids for mechanics that look similar but aren't the same item.
Verify against the real data rather than trusting the naming pattern alone.

---

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `CONTACT_EMAIL` | *(required)* | Your email, sent per GGG's required User-Agent format |
| `LEAGUE_NAME` | `Forbidden Rites` | Case-insensitive substring match against the API's `league` field |
| `REALM` | `poe2` | `poe2`, `xbox`, or `sony` |
| `MIN_VOLUME_PERCENTILE` | `0.90` | Self-scaling liquidity floor: only the top (1-p) share of that hour's pairs qualify |
| `MIN_VOLUME_ABS_FLOOR` | `20` | Hard minimum units, regardless of percentile, for quiet hours |
| `MIN_PROFIT_PCT` | `2.0` | Minimum conservative round-trip profit % to become a candidate |
| `PERSISTENCE_HOURS` | `2` | Consecutive qualifying hourly pulls required before alerting |
| `MAX_CYCLES_PER_RUN` | `8` | Cap on distinct cycles extracted per hour |
| `NTFY_TOPIC` | *(none)* | Free push notification topic, see 6.6 |
| `DISCORD_WEBHOOK_URL` | *(none)* | Optional Discord webhook for alerts |
| `HISTORY_KEEP` | `6` | How many past hourly summaries to retain in `state/history.json` |

---

## Limitations & honest caveats

- **Hourly aggregates, not live prices.** By the time a cycle is confirmed
  (2+ hours of persistence), the actual live rates in Faustus right now
  may have moved. Treat alerts as "worth checking right now," not
  guaranteed-still-there prices.
- **No real bid/ask spread data.** Faustus's actual buy/sell spread isn't
  separately exposed by this API; the conservative (worst-case-in-hour)
  rate is a reasonable proxy, but it's an approximation, not the literal fee.
- **Currency display names are best-effort**, not authoritative (see
  above) - the raw ids used for math are always exact.
- **New league, no data yet:** if `Forbidden Rites` hasn't started or has
  no trades yet, the tool will log which league names it *did* see that
  hour so you can fix `LEAGUE_NAME` if needed.
