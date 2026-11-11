# ShockPoint

**Know where a world event hits your business, and what to do about it.**

ShockPoint is a business decision-support system. It shows how an external global event hits one specific company, across its costs, margins, cash, production and customer deliveries. It then compares possible responses and recommends the best one. Every number traces back to a formula or a stated assumption.

`Global event → Business exposure → Impact simulation → Strategy comparison → Data-driven decision`

APU Cloud Innovation Hackathon 2026 · **Track 03: Data-Driven Research & Intelligent Decision Making**

**Deployed link:** `https://shockpoint.onrender.com` *(fill in after deploying; the free server sleeps when idle, so the first load can take about a minute)*

> **Simulated data.** The demo company (*Mutiara Control Systems Sdn Bhd*, Penang) and all supplier, order and event data are synthetic. Only the USD/MYR rate and the LME copper reference price in `data/assumptions.csv` are real, and their sources are cited there and in the app's Assumptions panel.

---

## Setup (each teammate)

```bash
git clone <repo-url> && cd shockpoint
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # paste GEMINI_API_KEY from Google AI Studio
python scripts/generate_data.py      # builds /data (fixed seed 42) and data/meta.json (the data date)
uvicorn backend.main:app --reload    # open http://localhost:8000
pytest                               # hand-checked formula tests
```

Python 3.11 to 3.13; `requirements.txt` pins the exact versions that were tested. The dashboard loads ECharts, MapLibre, Lucide and the Inter font from CDNs, so the browser needs internet access.

**Stable numbers:** the engine treats the date in `data/meta.json` as "today", so every figure stays the same until you regenerate the data. Use `python scripts/generate_data.py --as-of 2026-11-13` to pick the date.

The layout works on laptops, tablets and phones (below 820 px the side menu becomes a top bar).

Without a `GEMINI_API_KEY` the app still works. The AI features fall back to the engine's template text, labelled "Template summary (AI unavailable)".

## Deploy to Render (free)

1. Put the project in a **public GitHub repo** (upload through the GitHub website is fine). Do not upload `.env` or `.venv/`.
2. On [render.com](https://render.com), sign in with GitHub, then **New → Web Service** and pick the repo.
3. Language **Docker**, instance type **Free**. Leave the build and start commands empty; the `Dockerfile` handles both.
4. Under **Environment**, add `GEMINI_API_KEY` (your key) and `GEMINI_MODEL` = `gemini-3.8-flash`.
5. **Create Web Service.** The first build takes a few minutes, then the app is live at `https://<service-name>.onrender.com`.

- **One container:** the API and the frontend run together (see `Dockerfile`). Render sets `PORT`, and the app listens on it.
- **Sleeps when idle:** a free service stops after 15 minutes without visits and takes about a minute to wake up. Open the link before a demo.
- **Fresh dates:** the build re-runs `scripts/generate_data.py`, so order due dates fall in the next 60 days from build day. The values themselves never change.
- **API key:** the Gemini key lives only in Render's environment settings. It is never in the JavaScript, the repository or the image.
- **Other hosts:** the same `Dockerfile` runs on any Docker host, for example Google Cloud Run (`gcloud run deploy shockpoint --source .`).

## Repo structure

```
backend/   main.py (API routes + serves frontend/), schemas.py (Pydantic models), ai.py (all Gemini calls)
engine/    loader.py, exposure.py, simulate.py, strategies.py, decide.py, event_source.py
frontend/  index.html, css/theme.css, js/{app,api,overview,simulator,exposure,decision,monitor,charts,map}.js,
           data/world.json (offline map fallback)
data/      generated CSV + JSON, meta.json (data date)
scripts/   generate_data.py
tests/     test_engine.py
```

Rules:
- `engine/` is pure Python, with no FastAPI and no AI.
- The frontend never calculates; it only renders what the API returns.
- AI never produces a number.

## API

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness check: data loaded, data date, whether an AI key is set (never the key) |
| `GET /api/baseline` | Company, baseline KPIs, scenario definitions and slider ranges, strategies, assumptions, supplier exposure |
| `POST /api/simulate` | `{scenario_id, drivers}` → baseline vs scenario KPI cards, exposure, banner, top recommendation |
| `POST /api/decide` | `{scenario_id, drivers, weights}` → strategies ranked by weighted score, with the recommendation sentence |
| `GET /api/events?source=demo\|live` | Live Monitor feed: demo events, or real GDELT headlines mapped to a scenario (falls back to demo) |
| `POST /api/ai/brief` | Gemini executive briefing from the engine results (template fallback) |
| `POST /api/ai/parse-event` | Gemini turns a headline into scenario JSON via structured output. It fills every setting the headline mentions (place, severity, duration, freight; or demand drop, input prices, ringgit), quotes the words behind each value, and leaves the rest at their defaults. Values are clamped to the slider ranges; headlines that are not a modelled shock are rejected |
| `POST /api/ai/ask` | "Ask ShockPoint": a short answer grounded in the current results |

Interactive API docs are at `/docs`.

## KPI formulas (baseline vs scenario)

Every KPI card in the app has an **i** button. It shows the formula, the inputs used and their source.

| KPI | Formula | Scenario |
|---|---|---|
| Inventory runway (days) | stock on hand ÷ daily usage, per material | S1 |
| Supply gap (days) | new lead time − runway (production stops if > 0) | S1 |
| Production stop date | data date + runway, when new lead time > runway | S1 |
| Cost impact (RM) | Σ affected units × unit cost × price increase % + extra freight | S1, S2 |
| Gross margin (%) | (revenue − cost of goods) ÷ revenue | S1, S2 |
| Revenue at risk (RM) | value of orders due inside the supply gap window (S1), or cancelled by the demand drop (S2) | S1, S2 |
| Cash position (RM) | cash on hand − cost impact − strategy upfront cost | S1, S2 |
| Excess inventory (RM) | (stock − reduced usage × horizon days) × unit cost, if positive | S2 |
| Business risk level | Low / Medium / High from thresholds on margin drop and revenue at risk | S1, S2 |

How the engine reads each input:
- **New lead time:** supplier lead time + duration × severity %.
- **Affected units:** daily usage × the affected country's share × duration (S1), or the units on open purchase orders (S2).
- **Extra freight:** affected value × freight share (8%) × freight increase %.
- **Cash on hand:** projected to the end of the 60-day horizon. That is opening cash + revenue − material purchases − conversion − fixed costs.
- **Stock in the excess formula:** on-hand stock + open purchase orders in the horizon. The baseline open POs cover exactly the 60-day plan, so baseline excess is RM 0.
- **Risk thresholds:** listed in `assumptions.csv`.

## Decision engine

Each strategy is run through the same simulation and scored on four criteria. The user can change the weights with sliders in the app.

| Criterion | Measured as | Default weight |
|---|---|---|
| Value protected | extra gross profit vs doing nothing (RM); the margin on saved orders is counted once | 40% |
| Cost | upfront + ongoing cost of the strategy (RM), lower is better | 25% |
| Cash impact | cash position after the strategy, higher is better | 20% |
| Feasibility | time to take effect vs stockout date, and supplier capacity (0–1) | 15% |

`Score_s = Σ_c w_c · norm_c(s)`, where each criterion is min-max scaled from 0 to 1 across the strategies and the weights sum to 1.

"Do nothing" is always shown as a row, so judges can see the cost of inaction.

The top strategy gets one sentence built from a template filled with the numbers. Gemini then writes the executive briefing from the same results JSON.

## Scenarios

### S1: Port closure / shipping disruption (supply shock)

**Drivers:** affected place, severity (% capacity lost), duration, freight cost increase. The place is one of our supplier countries (China, Taiwan, South Korea, Japan, Vietnam) or **Malaysia: Penang Port**, where every import lands, so a closure there hits all suppliers. The title, map epicentre and precedent follow the place chosen.

**Responses adapt to the place.** "Buy early" and "Switch volume" pick the fastest alternative supplier that is outside the closed area, and are named after it (e.g. *Buy early from Changwon Power Devices (South Korea)*). If every alternative ships through the closed port, as in a Penang Port closure, they score zero and air freight comes out on top.

**Default result:**
- The PMIC (M02) runs out on day 16. Supply resumes on day 26.
- 5 orders worth RM 610k are at risk.
- Gross margin falls from 22.9% to 18.1%.

**Recommendation:** *"Buy early from Changwon Power Devices (South Korea): costs RM 9k now plus RM 2k over the horizon, protects RM 610k of orders, and arrives 7 days before stockout."*

**Precedents** (shown behind the **i** next to the banner title): Yantian, China, COVID shutdowns in 2021; Typhoon Krathon closing Kaohsiung and other Taiwan ports in October 2024; Typhoon Hinnamnor closing Busan, South Korea, in September 2022; Typhoon Jebi flooding Kobe's terminals, Japan, in September 2018; Super Typhoon Yagi closing Hai Phong, Vietnam, in September 2024. Penang Port has no full closure on record, so the app says that and cites the nearest case (monsoon floods around Port Klang, November 2025).

| Place (default 85%, 14 days) | Suppliers hit | Production stops? | Top response |
|---|---|---|---|
| China | 4 of 8 (50% of spend) | Yes, PMIC on day 16 | Buy early from Changwon (South Korea) |
| Taiwan, South Korea, Japan, Vietnam | 1 of 8 each | No, stock covers the delay | Do nothing |
| Malaysia: Penang Port | 8 of 8 | Yes, PMIC on day 16 | Air-freight critical parts |

### S2: Global electronics demand slump (demand shock)

**Drivers:** demand drop, input price change, ringgit vs USD change, supplier failure risk.

**Default result:**
- Excess inventory reaches RM 547k.
- Cash falls by RM 1.27M vs baseline.
- Margin falls from 22.9% to 9.5%.
- Two weaker suppliers are flagged as at risk.

**Recommendation:** *Cut purchase orders.* This is the opposite advice to S1: same engine, opposite decision.

**Precedent:** the 2022–23 chip inventory glut.

### Live Monitor (demo feed, simulated events)

Two sources, picked with a toggle:

- **Demo feed** (default): 6 timestamped demo headlines in `data/events_feed.json`. Always available; use it for the recorded demo.
- **Real headlines:** recent news from the free [GDELT DOC 2.0 API](https://api.gdeltproject.org/api/v2/doc/doc) (no key), last 7 days, in `backend/news.py`. Each headline goes through the same keyword rules as the headline box. Only those that map to a modelled shock are kept, with a link to the article. Results are cached for 30 minutes, because GDELT allows about one request every 5 seconds. If GDELT is slow, refuses the request, or no headline fits, the app shows the demo feed with a note saying why.

**Play feed** replays the events. Each one runs the normal simulation and raises the Overview banner.

## Dataset (`scripts/generate_data.py`, fixed seed)

| File | Contents |
|---|---|
| `company.csv` | 1 row: name, industry, city, cash, fixed cost, USD revenue share |
| `materials.csv` | 6 materials: stock, daily usage, safety stock, criticality 1–3 |
| `suppliers.csv` | 8 current + 4 alternative suppliers. Supply spend: China 50%, Taiwan 21%, South Korea 12%, Japan 9%, Vietnam 8%. Every sea route lands at Penang Port |
| `products.csv` | 3 products |
| `bom.csv` | 11 bill-of-materials rows |
| `orders.csv` | 28 orders due in the next 60 days (MYR/USD) |
| `scenarios.json` | 2 scenarios with defaults and slider ranges |
| `strategies.json` | 4 strategies per scenario + "Do nothing" |
| `assumptions.csv` | 20 assumptions with sources |
| `events_feed.json` | 6 demo events |

## AI guardrails

- The prompts tell Gemini to use only the numbers in the given JSON and never invent figures.
- A server-side check rejects any RM amount or % in the AI text that is not in the results. If one appears, the template is shown instead.
- Event parsing uses structured JSON-schema output, and the values are checked against the allowed lists and ranges. Each value comes with the headline words that set it, shown under "Event to scenario". Headlines outside the two modelled shocks (sports, company news, places we don't buy from) are rejected with a short reason. Without a key, keyword rules do the same job and say so.
- AI text is always labelled "AI-generated summary" with the model that answered (default `gemini-3.8-flash`; if it is busy, the app tries other Flash models). If Gemini fails or hits a rate limit, the template explanation appears instead, labelled "Template summary (AI unavailable)".
- Only synthetic data is ever sent to Gemini.

## Out of scope

Stock-market prediction, login and authentication, a global supplier database, and ML pipelines. These belong on the roadmap slide, along with Market Intelligence.
