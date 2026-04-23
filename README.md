# ⚡ JEG BALLISTIC AI — Gamma Breakout Engine
### Operation: JEG Ballistic AI | JEG Securities | Primary User: Everette

---

## What This Tool Does

JEG Ballistic AI is your daily trading intelligence system. Every morning it scans the market and answers:

1. **Which stocks are closest to a breakout?**
2. **Where are institutions positioning their options?**
3. **Where do gamma squeeze triggers sit?**
4. **Is volume expanding (confirming the move)?**
5. **What's the exact trade setup?**

It combines 4 signals into one score:
- **Technical Breakout (25%)** — flat tops, compression, EMA alignment
- **Gamma Positioning (30%)** — dealer hedging pressure, gamma triggers, call walls
- **Options Flow (25%)** — sweeps, blocks, call/put ratio, premium size
- **Volume Expansion (20%)** — relative volume, VWAP positioning

---

## Score Tiers

| Score | Tier | Action |
|-------|------|--------|
| 85+ | 🟢 ELITE SETUP | High conviction trade |
| 75–84 | 🟡 HIGH PROBABILITY | Enter with confirmation |
| 65–74 | 🔵 WATCHLIST | Monitor closely |

---

## How to Launch (No Coding Required)

### Step 1 — Install Python
Download Python from https://python.org (version 3.9 or higher)

### Step 2 — Open Terminal / Command Prompt
- **Mac**: Press Cmd+Space, type "Terminal", press Enter
- **Windows**: Press Win+R, type "cmd", press Enter

### Step 3 — Install the app
```
cd jeg_ballistic_ai
pip install -r requirements.txt
```

### Step 4 — Run the app
```
streamlit run app.py
```

Your browser will open automatically at http://localhost:8501

---

## How to Use

1. **Sidebar** — Select which tickers to scan (default: top 15 liquid names)
2. **Min Score Filter** — Slide to filter for only the best setups
3. **FIRE SCAN button** — Run the scan (auto-runs on load)
4. **Tabs:**
   - **WATCHLIST** — Ranked results with trade ideas + CSV export
   - **GAMMA MAP** — Visual GEX profile per ticker
   - **SCORE BREAKDOWN** — Charts showing signal distribution and radar
   - **TICKER DETAIL** — Deep dive with price levels and waterfall scoring

---

## Data Providers (for live data — future integration)

| Provider | Data Type | Notes |
|----------|-----------|-------|
| Polygon.io | Price, options chains | Recommended for MVP |
| Tradier | Options flow | Good free tier |
| Unusual Whales | Institutional flow | Best sweep data |
| Theta Data | Historical options | Backtesting |

---

## Scheduled Scans (Production Roadmap)

| Time (ET) | Action |
|-----------|--------|
| 7:55 AM | Refresh universe + warm cache |
| 8:00 AM | Pre-market full scan |
| 8:15 AM | Publish ranked watchlist |
| 9:35 AM | Post-open confirmation |
| Every 5 min | Rescan top watchlist |
| 4:15 PM | Archive results |

---

## Project Structure
```
jeg_ballistic_ai/
├── app.py              ← Main dashboard (run this)
├── requirements.txt    ← Python dependencies
└── README.md           ← This file
```

---

*JEG Ballistic AI — For JEG Securities Internal Use Only*
*Version 1.0 MVP | Owner: JEG Securities | Primary User: Everette*
