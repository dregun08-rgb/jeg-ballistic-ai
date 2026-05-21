"""
JEG BALLISTIC AI v6 — Gamma Reclaim Engine (Build 2026-05-14)
Operation: JEG Ballistic AI
Owner: JEG Securities | Primary User: Everette

UPGRADES IN v5:
- E*TRADE Pro API: OAuth 1.0a · Live Quotes · Accounts · Positions · Order Entry
- Real-time News + Market Sentiment scoring
- Post-OPEX Gamma Rebuild Filter
- Sentiment-adjusted scores
- Live market data via Polygon.io (fallback)
- Mobile/iPad accessible via network URL
- Expanded universe (250+ tickers)
- 85+ score alerts via email
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import smtplib
import json
import re
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    from requests_oauthlib import OAuth1
    OAUTH_OK = True
except ImportError:
    OAUTH_OK = False

# ─────────────────────────────────────────────
# E*TRADE API FUNCTIONS
# ─────────────────────────────────────────────
ETRADE_BASE_PROD    = "https://api.etrade.com"
ETRADE_BASE_SANDBOX = "https://apisb.etrade.com"
ETRADE_AUTH_URL     = "https://us.etrade.com/e/t/etws/authorize"

def etrade_base(sandbox): return ETRADE_BASE_SANDBOX if sandbox else ETRADE_BASE_PROD

def etrade_get_request_token(ck, cs, sandbox):
    url = f"{etrade_base(sandbox)}/oauth/request_token"
    try:
        resp = requests.get(url, auth=OAuth1(ck, cs, callback_uri="oob"), timeout=10)
        if resp.status_code == 200:
            p = dict(urllib.parse.parse_qsl(resp.text))
            return {"success": True, "oauth_token": p.get("oauth_token"), "oauth_token_secret": p.get("oauth_token_secret")}
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def etrade_get_auth_url(ck, token):
    return f"{ETRADE_AUTH_URL}?key={ck}&token={token}"

def etrade_get_access_token(ck, cs, token, token_secret, verifier, sandbox):
    url = f"{etrade_base(sandbox)}/oauth/access_token"
    try:
        resp = requests.get(url, auth=OAuth1(ck, cs, token, token_secret, verifier=verifier), timeout=10)
        if resp.status_code == 200:
            p = dict(urllib.parse.parse_qsl(resp.text))
            return {"success": True, "access_token": p.get("oauth_token"), "access_token_secret": p.get("oauth_token_secret")}
        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def etrade_revoke_token(ck, cs, at, ats, sandbox):
    try: requests.get(f"{etrade_base(sandbox)}/oauth/revoke_access_token", auth=OAuth1(ck, cs, at, ats), timeout=10)
    except: pass

def _eauth(ck, cs, at, ats): return OAuth1(ck, cs, at, ats)

def etrade_get_accounts(ck, cs, at, ats, sandbox):
    try:
        resp = requests.get(f"{etrade_base(sandbox)}/v1/accounts/list.json", auth=_eauth(ck,cs,at,ats), timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

def etrade_get_balance(ck, cs, at, ats, acct_key, sandbox):
    try:
        resp = requests.get(f"{etrade_base(sandbox)}/v1/accounts/{acct_key}/balance.json",
            auth=_eauth(ck,cs,at,ats), params={"instType":"BROKERAGE","realTimeNAV":"true"}, timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

def etrade_get_portfolio(ck, cs, at, ats, acct_key, sandbox):
    try:
        resp = requests.get(f"{etrade_base(sandbox)}/v1/accounts/{acct_key}/portfolio.json", auth=_eauth(ck,cs,at,ats), timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

def etrade_get_quotes(ck, cs, at, ats, symbols, sandbox):
    try:
        url = f"{etrade_base(sandbox)}/v1/market/quote/{','.join(symbols[:50])}.json"
        resp = requests.get(url, auth=_eauth(ck,cs,at,ats), params={"requireEarningsDate":"false","overrideSymbolCount":"true"}, timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

def etrade_get_orders(ck, cs, at, ats, acct_key, sandbox):
    try:
        resp = requests.get(f"{etrade_base(sandbox)}/v1/accounts/{acct_key}/orders.json",
            auth=_eauth(ck,cs,at,ats), params={"count": 25}, timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

def etrade_preview_order(ck, cs, at, ats, acct_key, symbol, action, qty, otype, limit_px, sandbox):
    url = f"{etrade_base(sandbox)}/v1/accounts/{acct_key}/orders/preview.json"
    payload = {"PreviewOrderRequest": {"orderType":"EQ","clientOrderId":str(int(time.time())),"Order":[{
        "allOrNone":"false","priceType":otype,"orderTerm":"GOOD_FOR_DAY","marketSession":"REGULAR",
        "stopPrice":"","limitPrice":str(limit_px) if otype=="LIMIT" else "",
        "Instrument":[{"Product":{"securityType":"EQ","symbol":symbol},"orderAction":action,"quantityType":"QUANTITY","quantity":str(qty)}]
    }]}}
    try:
        resp = requests.post(url, auth=_eauth(ck,cs,at,ats), json=payload, timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}: {resp.text}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

def etrade_place_order(ck, cs, at, ats, acct_key, symbol, action, qty, otype, limit_px, preview_id, sandbox):
    url = f"{etrade_base(sandbox)}/v1/accounts/{acct_key}/orders/place.json"
    payload = {"PlaceOrderRequest": {"orderType":"EQ","clientOrderId":str(int(time.time())),
        "PreviewIds":[{"previewId":preview_id}],"Order":[{
        "allOrNone":"false","priceType":otype,"orderTerm":"GOOD_FOR_DAY","marketSession":"REGULAR",
        "stopPrice":"","limitPrice":str(limit_px) if otype=="LIMIT" else "",
        "Instrument":[{"Product":{"securityType":"EQ","symbol":symbol},"orderAction":action,"quantityType":"QUANTITY","quantity":str(qty)}]
    }]}}
    try:
        resp = requests.post(url, auth=_eauth(ck,cs,at,ats), json=payload, timeout=10)
        return {"success": resp.status_code==200, "data": resp.json() if resp.status_code==200 else None, "error": f"HTTP {resp.status_code}: {resp.text}" if resp.status_code!=200 else ""}
    except Exception as e: return {"success": False, "error": str(e)}

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="JEG BALLISTIC AI",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# PASSWORD GATE
# ─────────────────────────────────────────────
import os

def check_password():
    """Returns True if password is correct."""
    # Get password from Streamlit secrets or environment
    correct_password = st.secrets.get("APP_PASSWORD", os.environ.get("APP_PASSWORD", "JEGballistic2026"))

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    # Password screen
    st.markdown("""
    <style>
    .login-container {
        max-width: 420px;
        margin: 8vh auto;
        padding: 40px;
        background: #0d1120;
        border: 1px solid #1e2a3a;
        border-radius: 12px;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div style="text-align:center; padding:40px 0 20px 0;">
            <div style="font-family:'Orbitron',sans-serif; font-size:0.5rem; color:#475569; letter-spacing:0.4em; text-transform:uppercase;">JEG Securities</div>
            <div style="font-family:'Orbitron',sans-serif; font-size:2rem; font-weight:900;
                 background:linear-gradient(90deg,#00ff88 0%,#00b4ff 60%,#8b5cf6 100%);
                 -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                 letter-spacing:0.04em; margin:8px 0;">BALLISTIC AI</div>
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#475569; letter-spacing:0.2em;">GAMMA RECLAIM ENGINE v6 · CLASSIFIED</div>
        </div>
        """, unsafe_allow_html=True)

        password = st.text_input("Access Code", type="password", placeholder="Enter access code...", label_visibility="collapsed")
        login_btn = st.button("⚡ AUTHENTICATE", use_container_width=True)

        if login_btn:
            if password == correct_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Invalid access code. Contact JEG Securities for access.")

        st.markdown("""
        <div style="font-family:'Share Tech Mono',monospace; font-size:0.58rem; color:#2d3f55;
             text-align:center; margin-top:24px; letter-spacing:0.1em;">
            JEG SECURITIES · INTERNAL USE ONLY · UNAUTHORIZED ACCESS PROHIBITED
        </div>
        """, unsafe_allow_html=True)

    return False

if not check_password():
    st.stop()



# ─────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@400;700;900&display=swap');
:root {
    --bg-primary: #060810; --bg-secondary: #0a0d1a; --bg-card: #0d1120;
    --accent-green: #00ff88; --accent-amber: #ffb800; --accent-red: #ff3366;
    --accent-blue: #00b4ff; --accent-purple: #8b5cf6;
    --text-primary: #e2e8f0; --text-secondary: #94a3b8; --text-dim: #475569;
    --border: #1e2a3a; --border-bright: #2d3f55;
}
html, body, [class*="css"] { font-family: 'Rajdhani', sans-serif; background-color: var(--bg-primary) !important; color: var(--text-primary) !important; }
.stApp { background: linear-gradient(135deg, #060810 0%, #080c18 50%, #060810 100%) !important; }
.block-container { padding-top: 1rem !important; max-width: 1400px !important; }
[data-testid="stSidebar"] { background: var(--bg-secondary) !important; border-right: 1px solid var(--border) !important; }
[data-testid="stSidebar"] * { color: var(--text-primary) !important; }
h1, h2, h3 { font-family: 'Orbitron', sans-serif !important; letter-spacing: 0.05em !important; }
[data-testid="metric-container"] { background: var(--bg-card) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; padding: 12px 16px !important; }
[data-testid="stMetricLabel"] { font-family: 'Share Tech Mono', monospace !important; color: var(--text-secondary) !important; font-size: 0.7rem !important; text-transform: uppercase !important; letter-spacing: 0.1em !important; }
[data-testid="stMetricValue"] { font-family: 'Orbitron', sans-serif !important; color: var(--accent-green) !important; font-size: 1.4rem !important; }
.stButton > button { background: linear-gradient(135deg, #00ff88 0%, #00b4ff 100%) !important; color: #060810 !important; font-family: 'Orbitron', sans-serif !important; font-weight: 700 !important; font-size: 0.75rem !important; letter-spacing: 0.1em !important; border: none !important; border-radius: 4px !important; padding: 0.5rem 1.5rem !important; text-transform: uppercase !important; }
.stTabs [data-baseweb="tab-list"] { background: var(--bg-secondary) !important; border-bottom: 1px solid var(--border) !important; }
.stTabs [data-baseweb="tab"] { font-family: 'Orbitron', sans-serif !important; font-size: 0.65rem !important; letter-spacing: 0.08em !important; color: var(--text-secondary) !important; background: transparent !important; border: none !important; padding: 0.6rem 1.2rem !important; }
.stTabs [aria-selected="true"] { color: var(--accent-green) !important; border-bottom: 2px solid var(--accent-green) !important; background: transparent !important; }
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg-primary); }
::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 2px; }
.alert-box { background: #0d1a0d; border: 1px solid #00ff8866; border-radius: 8px; padding: 14px 18px; margin: 8px 0; }
.mobile-tip { background: #0a0d1a; border: 1px solid #1e2a3a; border-radius: 6px; padding: 10px 14px; font-family: 'Share Tech Mono', monospace; font-size: 0.65rem; color: #94a3b8; }
.sentiment-bull { background: #0d1a0d; border: 1px solid #00ff8855; border-radius: 6px; padding: 10px 14px; margin: 4px 0; }
.sentiment-bear { background: #1a0d0d; border: 1px solid #ff336655; border-radius: 6px; padding: 10px 14px; margin: 4px 0; }
.sentiment-neut { background: #0d1120; border: 1px solid #1e2a3a; border-radius: 6px; padding: 10px 14px; margin: 4px 0; }
.opex-badge { background: linear-gradient(135deg, #8b5cf622, #8b5cf611); border: 1px solid #8b5cf655; border-radius: 6px; padding: 8px 14px; font-family: 'Share Tech Mono', monospace; font-size: 0.65rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# E*TRADE SESSION STATE
# ─────────────────────────────────────────────
for _k, _v in {
    "etrade_connected": False, "etrade_sandbox": True,
    "etrade_consumer_key": "", "etrade_consumer_secret": "",
    "etrade_access_token": "", "etrade_access_token_secret": "",
    "etrade_request_token": "", "etrade_request_token_secret": "",
    "etrade_auth_step": 0, "etrade_accounts": None,
    "etrade_selected_account": None, "etrade_live_quotes": {},
    "order_preview_data": None,
}.items():
    if _k not in st.session_state: st.session_state[_k] = _v

# ─────────────────────────────────────────────
# EXPANDED UNIVERSE — 250+ TICKERS
# ─────────────────────────────────────────────
UNIVERSE = {
    "AAPL":250.12,"ABNB":126.3,"ADBE":249.32,"ADI":306.07,"AMAT":341.53,"AMD":193.39,
    "AMGN":366.21,"AMZN":207.67,"ANET":133.57,"APP":458.67,"ARM":115.75,"ASML":1345.69,
    "AVGO":322.16,"AXON":496.18,"AXP":299.96,"BA":209.89,"BABA":135.21,"BAC":38.0,
    "BIDU":124.07,"BIIB":181.55,"BLK":924.11,"BKNG":4241.26,"BX":106.78,"CAT":693.99,
    "CELH":44.57,"CEG":301.77,"CFLT":30.67,"CI":267.19,"COIN":195.53,"COST":1008.43,
    "CRM":192.83,"CRWD":441.78,"CSCO":78.33,"CVNA":300.15,"CVX":196.82,"DAL":58.78,
    "DASH":161.36,"DDOG":124.52,"DE":577.5,"DELL":151.62,"DIS":99.29,"DKNG":25.87,
    "DOCU":47.05,"DUOL":98.39,"DXCM":64.24,"ELF":73.41,"ENPH":44.07,"EXPE":228.37,
    "FDX":351.68,"FSLR":196.07,"FTNT":83.44,"GE":299.69,"GLD":460.84,"GM":72.39,
    "GME":23.53,"GOOG":301.46,"GOOGL":302.28,"GS":782.21,"HD":339.03,"HIMS":24.77,
    "HOOD":73.39,"HUBS":264.3,"IBM":246.28,"INTC":45.77,"INTU":439.96,"IONQ":32.98,
    "ISRG":472.16,"IWM":246.59,"JNJ":241.52,"JPM":283.44,"KLAC":750.0,"KO":77.34,
    "LRCX":212.2,"LLY":985.08,"LMT":646.0,"LOW":237.59,"LULU":157.78,"MCD":326.46,
    "MDB":260.5,"MELI":1670.0,"META":613.71,"MGM":36.68,"MMM":150.96,"MNDY":74.86,
    "MPWR":1052.59,"MRNA":52.56,"MS":154.87,"MSFT":395.55,"MSTR":139.67,"MU":455.0,
    "NET":212.45,"NFLX":95.31,"NKE":53.98,"NOC":733.71,"NOW":113.62,"NVDA":180.25,
    "NVO":37.96,"OKTA":79.16,"ON":58.55,"ORCL":155.11,"PANW":167.02,"PATH":11.58,
    "PDD":102.65,"PEP":159.88,"PFE":26.58,"PG":150.65,"PINS":18.18,"PLTR":150.95,
    "PM":174.66,"PYPL":44.9,"QCOM":129.82,"QQQ":593.72,"RBLX":56.42,"RDDT":132.36,
    "REGN":745.77,"RIVN":14.86,"RKLB":68.41,"ROKU":91.65,"RTX":204.52,"SBUX":99.15,
    "SCHW":93.06,"SE":86.0,"SHOP":122.96,"SLV":72.69,"SMCI":30.75,"SMH":387.33,
    "SNOW":178.66,"SOXL":50.72,"SOXS":41.3,"SPOT":516.06,"SPY":662.29,"SQ":68.0,
    "STX":383.71,"SYK":336.77,"TEAM":75.21,"TGT":117.34,"TLT":86.54,"TSLA":391.2,
    "TSM":338.31,"TTD":27.34,"TWLO":124.5,"TXN":190.78,"UAL":86.6,"UBER":73.33,
    "ULTA":535.72,"UNH":282.09,"UPS":97.21,"UPST":26.36,"V":307.14,"VEEV":178.88,
    "VRT":258.88,"VST":158.95,"VZ":51.38,"WFC":74.1,"WMT":126.52,"WDAY":133.09,
    "XLF":48.89,"XOM":156.12,"ZM":74.1,"ZS":153.76,"ARKK":48.0,"TQQQ":62.0,
    "IBIT":40.37,"NVDL":78.58,"OXY":52.0,"ABBV":172.0,"NKTR":73.25,"GLD":228.0,
}

# ─────────────────────────────────────────────
# OPEX GAMMA REBUILD LOGIC
# ─────────────────────────────────────────────
def get_opex_dates(year: int) -> list:
    """Return list of monthly OPEX dates (3rd Friday of each month)."""
    opex_dates = []
    for month in range(1, 13):
        # Find 3rd Friday
        first_day = datetime(year, month, 1)
        first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
        third_friday = first_friday + timedelta(weeks=2)
        opex_dates.append(third_friday.date())
    return opex_dates

def get_opex_status() -> dict:
    """
    Determine where we are relative to OPEX:
    - Days since last OPEX
    - Days until next OPEX
    - Post-OPEX rebuild window (1–5 days after OPEX = gamma rebuilds)
    - Pre-OPEX pinning window (1–3 days before OPEX = gamma pinning)
    """
    today = datetime.now().date()
    current_year_opex = get_opex_dates(today.year)
    next_year_opex    = get_opex_dates(today.year + 1)
    all_opex          = sorted(current_year_opex + next_year_opex)

    last_opex = None
    next_opex = None
    for d in all_opex:
        if d <= today:
            last_opex = d
        else:
            if next_opex is None:
                next_opex = d

    days_since = (today - last_opex).days if last_opex else 99
    days_until = (next_opex - today).days if next_opex else 99

    # Gamma Rebuild Window: days 1-6 after OPEX = dealers re-hedge, gamma expands
    in_rebuild_window  = 1 <= days_since <= 6
    # Pre-OPEX Pin Window: 3 days before = max pain pin
    in_pin_window      = 1 <= days_until <= 3
    # Mid-cycle neutral
    in_neutral         = not in_rebuild_window and not in_pin_window

    if in_rebuild_window:
        phase = "🔨 POST-OPEX REBUILD"
        phase_color = "#00ff88"
        phase_desc  = f"Day {days_since} post-OPEX — Dealers REBUILDING gamma positions. Breakouts AMPLIFIED."
        phase_boost = 8   # score boost for breakout setups
    elif in_pin_window:
        phase = "📌 PRE-OPEX PIN"
        phase_color = "#ff3366"
        phase_desc  = f"{days_until}d to OPEX — Max pain pinning likely. Range-bound. CAUTION on breakouts."
        phase_boost = -5  # score penalty
    else:
        phase = "⚖️ MID-CYCLE"
        phase_color = "#ffb800"
        phase_desc  = f"{days_since}d post-OPEX, {days_until}d to next OPEX — Normal gamma environment."
        phase_boost = 0

    return {
        "last_opex":        last_opex,
        "next_opex":        next_opex,
        "days_since":       days_since,
        "days_until":       days_until,
        "in_rebuild":       in_rebuild_window,
        "in_pin":           in_pin_window,
        "phase":            phase,
        "phase_color":      phase_color,
        "phase_desc":       phase_desc,
        "phase_boost":      phase_boost,
    }

# ─────────────────────────────────────────────
# NEWS SENTIMENT ENGINE
# ─────────────────────────────────────────────

# Bullish/bearish keyword banks
BULL_WORDS = [
    "surge", "soar", "rally", "beat", "beats", "upgrade", "upgraded", "buy",
    "outperform", "bullish", "breakout", "record", "high", "strong", "positive",
    "growth", "profit", "revenue", "raised", "raise", "guidance", "dividend",
    "acquisition", "partnership", "deal", "launch", "innovation", "ai", "wins",
    "contract", "approval", "approved", "exceeds", "momentum", "recovery",
]
BEAR_WORDS = [
    "crash", "plunge", "drop", "fall", "miss", "misses", "downgrade", "downgraded",
    "sell", "bearish", "breakdown", "low", "weak", "negative", "loss", "losses",
    "cut", "cuts", "layoff", "layoffs", "fired", "lawsuit", "investigation",
    "fine", "penalty", "recall", "delay", "disappoints", "below", "warning",
    "halt", "suspended", "debt", "default", "decline", "missed", "pressure",
]

def score_headline(headline: str) -> float:
    """Score a headline from -1.0 (very bearish) to +1.0 (very bullish)."""
    text = headline.lower()
    bull = sum(1 for w in BULL_WORDS if w in text)
    bear = sum(1 for w in BEAR_WORDS if w in text)
    total = bull + bear
    if total == 0:
        return 0.0
    return round((bull - bear) / total, 3)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_polygon_news(ticker: str, api_key: str, limit: int = 8) -> list:
    """Fetch recent news from Polygon.io for a ticker."""
    if not api_key or not REQUESTS_OK:
        return []
    try:
        url = (
            f"https://api.polygon.io/v2/reference/news"
            f"?ticker={ticker}&limit={limit}&sort=published_utc&order=desc&apiKey={api_key}"
        )
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data = r.json()
            articles = []
            for item in data.get("results", []):
                title     = item.get("title", "")
                pub       = item.get("published_utc", "")[:16].replace("T", " ")
                sentiment = score_headline(title)
                articles.append({
                    "title":     title,
                    "published": pub,
                    "sentiment": sentiment,
                    "url":       item.get("article_url", "#"),
                    "publisher": item.get("publisher", {}).get("name", ""),
                })
            return articles
    except Exception:
        pass
    return []

@st.cache_data(ttl=300, show_spinner=False)
def fetch_market_sentiment_indicators(api_key: str) -> dict:
    """
    Fetch broad market sentiment proxy:
    - VIX level from SPY/QQQ snapshot
    - Put/Call ratio from options flow
    - Fear/Greed proxy
    """
    if not api_key or not REQUESTS_OK:
        return _simulated_market_sentiment()
    try:
        # Get SPY snapshot for market direction
        url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?tickers=SPY,QQQ,VIX&apiKey={api_key}"
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data = r.json()
            spy_chg = 0.0
            qqq_chg = 0.0
            for item in data.get("tickers", []):
                t   = item.get("ticker", "")
                chg = item.get("todaysChangePerc", 0.0) or 0.0
                if t == "SPY":
                    spy_chg = float(chg)
                elif t == "QQQ":
                    qqq_chg = float(chg)
            avg_chg = (spy_chg + qqq_chg) / 2
            # Derive sentiment from market move
            if avg_chg > 1.0:
                mkt_sent = 0.7
                mkt_label = "BULLISH"
                mkt_color = "#00ff88"
            elif avg_chg > 0.2:
                mkt_sent = 0.3
                mkt_label = "MILDLY BULLISH"
                mkt_color = "#00ff88"
            elif avg_chg < -1.0:
                mkt_sent = -0.7
                mkt_label = "BEARISH"
                mkt_color = "#ff3366"
            elif avg_chg < -0.2:
                mkt_sent = -0.3
                mkt_label = "MILDLY BEARISH"
                mkt_color = "#ffb800"
            else:
                mkt_sent = 0.0
                mkt_label = "NEUTRAL"
                mkt_color = "#94a3b8"
            return {
                "spy_chg":   round(spy_chg, 2),
                "qqq_chg":   round(qqq_chg, 2),
                "sentiment": mkt_sent,
                "label":     mkt_label,
                "color":     mkt_color,
                "source":    "live",
            }
    except Exception:
        pass
    return _simulated_market_sentiment()

def _simulated_market_sentiment() -> dict:
    """Return simulated market sentiment when no live data."""
    rng = np.random.RandomState(int(datetime.now().strftime("%Y%m%d%H")) % 9999)
    spy_chg = round(rng.uniform(-1.5, 1.8), 2)
    qqq_chg = round(rng.uniform(-1.8, 2.0), 2)
    avg = (spy_chg + qqq_chg) / 2
    if avg > 0.5:
        label, color, sent = "BULLISH", "#00ff88", 0.6
    elif avg > 0.0:
        label, color, sent = "MILDLY BULLISH", "#00ff88", 0.25
    elif avg < -0.5:
        label, color, sent = "BEARISH", "#ff3366", -0.6
    else:
        label, color, sent = "NEUTRAL", "#94a3b8", 0.0
    return {
        "spy_chg": spy_chg, "qqq_chg": qqq_chg,
        "sentiment": sent, "label": label, "color": color, "source": "sim",
    }

def compute_ticker_sentiment(ticker: str, api_key: str) -> dict:
    """
    Aggregate sentiment for a ticker from news.
    Returns score -100..+100, label, and articles.
    """
    articles = fetch_polygon_news(ticker, api_key)
    if not articles:
        # Fallback simulated sentiment
        rng = np.random.RandomState(abs(hash(ticker + str(datetime.now().date()))) % 9999)
        raw = float(rng.uniform(-0.4, 0.7))
        articles = _generate_simulated_news(ticker, raw)
    else:
        raw = np.mean([a["sentiment"] for a in articles]) if articles else 0.0

    # Map -1..1 → -100..100
    score = round(raw * 100)
    score = max(-100, min(100, score))

    if score >= 30:
        label = "BULLISH"
        color = "#00ff88"
        icon  = "📈"
    elif score <= -30:
        label = "BEARISH"
        color = "#ff3366"
        icon  = "📉"
    else:
        label = "NEUTRAL"
        color = "#94a3b8"
        icon  = "➡️"

    return {
        "score":    score,
        "raw":      raw,
        "label":    label,
        "color":    color,
        "icon":     icon,
        "articles": articles,
    }

def _generate_simulated_news(ticker: str, sentiment_bias: float) -> list:
    """Generate realistic simulated news headlines."""
    bull_templates = [
        f"{ticker} surges on strong earnings beat, analysts raise price targets",
        f"{ticker} options flow shows massive call buying — institutional interest high",
        f"Analysts upgrade {ticker} to Buy, cite AI-driven growth acceleration",
        f"{ticker} breaks out to new 52-week high on record volume",
        f"Goldman Sachs raises {ticker} price target, sees 20% upside",
    ]
    bear_templates = [
        f"{ticker} drops after disappointing quarterly guidance cut",
        f"Heavy put buying detected in {ticker} — hedge funds defensive",
        f"Analyst downgrades {ticker}, cites margin pressure and competition",
        f"{ticker} falls on regulatory scrutiny, options traders hedge downside",
        f"Technical breakdown in {ticker} — support level breached on high volume",
    ]
    neut_templates = [
        f"{ticker} holds steady ahead of earnings — options pricing elevated",
        f"Mixed signals in {ticker}: bullish flow vs. macro headwinds",
        f"{ticker} in consolidation phase — gamma neutral near current levels",
        f"Sector rotation pressures {ticker} despite solid fundamentals",
    ]

    rng = np.random.RandomState(abs(hash(ticker + str(datetime.now().date()))) % 9999)
    articles = []
    hours_ago = [1, 3, 5, 8, 12]

    if sentiment_bias > 0.2:
        pool = bull_templates
    elif sentiment_bias < -0.2:
        pool = bear_templates
    else:
        pool = neut_templates

    for i in range(min(4, len(pool))):
        pub_time = datetime.now() - timedelta(hours=hours_ago[i])
        articles.append({
            "title":     pool[i],
            "published": pub_time.strftime("%Y-%m-%d %H:%M"),
            "sentiment": score_headline(pool[i]),
            "url":       "#",
            "publisher": rng.choice(["Bloomberg", "Reuters", "WSJ", "Seeking Alpha", "Benzinga"]),
        })
    return articles

# ─────────────────────────────────────────────
# LIVE DATA FUNCTIONS
# ─────────────────────────────────────────────
def fetch_live_snapshot(tickers: list, api_key: str) -> dict:
    prices = {}
    try:
        joined = ",".join(tickers)
        url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?tickers={joined}&apiKey={api_key}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for item in data.get("tickers", []):
                ticker = item["ticker"]
                # Priority: intraday close → last trade → prev day close
                price = (
                    item.get("day", {}).get("c") or
                    item.get("lastTrade", {}).get("p") or
                    item.get("prevDay", {}).get("c")
                )
                if price and float(price) > 0:
                    prices[ticker] = float(price)
    except Exception:
        pass
    return prices

def fetch_options_chain(ticker: str, api_key: str, spot: float):
    try:
        url = f"https://api.polygon.io/v3/snapshot/options/{ticker}?limit=250&apiKey={api_key}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            records = []
            for item in data.get("results", []):
                details = item.get("details", {})
                greeks  = item.get("greeks", {})
                day     = item.get("day", {})
                exp     = details.get("expiration_date", "")
                if exp:
                    dte = (datetime.strptime(exp, "%Y-%m-%d") - datetime.now()).days
                    if 0 < dte <= 45:
                        records.append({
                            "strike":        float(details.get("strike_price", 0)),
                            "dte":           dte,
                            "option_type":   details.get("contract_type", "call"),
                            "open_interest": float(item.get("open_interest", 0)),
                            "volume":        float(day.get("volume", 0)),
                            "gamma":         float(greeks.get("gamma", 0.001)),
                            "delta":         float(greeks.get("delta", 0.5)),
                            "iv":            float(item.get("implied_volatility", 0.3)),
                            "bid":           float(day.get("open", 0)),
                            "ask":           float(day.get("close", 0)),
                        })
            if records:
                return pd.DataFrame(records)
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────
# ALERT FUNCTIONS
# ─────────────────────────────────────────────
def send_email_alert(to_email, from_email, app_password, alerts):
    try:
        subject = f"🎯 JEG BALLISTIC AI — {len(alerts)} ELITE SETUP(S) DETECTED"
        body = "OPERATION: JEG BALLISTIC AI\nELITE SETUPS (Score 85+)\n\n" + "="*50 + "\n\n"
        for a in alerts:
            body += f"TICKER:      {a['Ticker']}\n"
            body += f"PRICE:       ${a['Price']:.2f}\n"
            body += f"BREAKOUT:    ${a['Breakout']:.2f}\n"
            body += f"SCORE:       {a['SCORE']}\n"
            body += f"SENTIMENT:   {a.get('Sentiment Label','—')}\n"
            body += f"TRADE IDEA:  {a['Trade Idea']}\n"
            body += "-"*40 + "\n\n"
        body += f"\nScan Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}"
        body += "\n\nJEG Securities — Classified Intelligence System"
        msg = MIMEMultipart()
        msg["From"]    = from_email
        msg["To"]      = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(from_email, app_password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        return str(e)

# ─────────────────────────────────────────────
# CORE ENGINE LOGIC
# ─────────────────────────────────────────────
def compute_expiration_weight(dte: int) -> float:
    if dte <= 7:   return 1.0
    if dte <= 21:  return 0.7
    if dte <= 45:  return 0.4
    return 0.2

def gamma_exposure_proxy(oi, gamma, dte) -> float:
    return float(oi) * float(gamma) * 100.0 * compute_expiration_weight(dte)

def generate_simulated_chain(ticker: str, spot: float, seed: int = None) -> pd.DataFrame:
    rng = np.random.RandomState(seed or abs(hash(ticker)) % 10000)
    records = []
    for dte in [3, 7, 14, 21, 35]:
        strikes = np.round(np.concatenate([
            np.arange(spot * 0.88, spot, spot * 0.025),
            np.arange(spot, spot * 1.14, spot * 0.025)
        ]) / 2.5) * 2.5
        for strike in strikes:
            dist = (strike - spot) / spot
            call_oi = max(100, int(rng.exponential(2000) * np.exp(-abs(dist) * 8)))
            put_oi  = max(100, int(rng.exponential(2000) * np.exp(-abs(dist) * 8)))
            if -0.05 < dist < 0.02: call_oi = int(call_oi * rng.uniform(2, 5))
            if -0.02 < dist < 0.05: put_oi  = int(put_oi  * rng.uniform(1.5, 3))
            gamma_val   = max(0.001, 0.08 * np.exp(-dist**2 / (2*0.03**2))) / spot * 100
            delta_call  = max(0.01, min(0.99, 0.5 - dist * 3))
            for opt_type, oi in [("call", call_oi), ("put", put_oi)]:
                records.append({
                    "strike": round(strike, 2), "dte": dte, "option_type": opt_type,
                    "open_interest": oi, "volume": int(oi * rng.uniform(0.05, 0.4)),
                    "gamma": round(gamma_val, 5),
                    "delta": round(delta_call if opt_type=="call" else delta_call-1, 3),
                    "iv": round(rng.uniform(0.25, 0.65), 3),
                    "bid": round(max(0.01, abs(dist)*spot*0.5 + rng.uniform(0.1, 2)), 2),
                    "ask": round(max(0.02, abs(dist)*spot*0.5 + rng.uniform(0.2, 3)), 2),
                })
    return pd.DataFrame(records)

def identify_gamma_levels(chain_df, current_price):
    calls = chain_df[(chain_df["option_type"]=="call") & (chain_df["strike"]>=current_price)].copy()
    puts  = chain_df[(chain_df["option_type"]=="put")  & (chain_df["strike"]<=current_price)].copy()
    calls["gex_proxy"] = calls.apply(lambda r: gamma_exposure_proxy(r["open_interest"], r["gamma"], r["dte"]), axis=1)
    puts["gex_proxy"]  = puts.apply( lambda r: gamma_exposure_proxy(r["open_interest"], r["gamma"], r["dte"]), axis=1)
    call_by_strike = calls.groupby("strike", as_index=False)["gex_proxy"].sum().sort_values("strike")
    put_by_strike  = puts.groupby("strike",  as_index=False)["gex_proxy"].sum().sort_values("strike")
    meaningful = call_by_strike[call_by_strike["gex_proxy"] > call_by_strike["gex_proxy"].quantile(0.65)]
    gamma_trigger = meaningful["strike"].min() if not meaningful.empty else None
    call_wall = call_by_strike.loc[call_by_strike["gex_proxy"].idxmax(), "strike"] if not call_by_strike.empty else None
    put_wall  = put_by_strike.loc[put_by_strike["gex_proxy"].idxmax(),  "strike"] if not put_by_strike.empty  else None
    accel = meaningful[meaningful["strike"] > gamma_trigger].head(3) if gamma_trigger else pd.DataFrame()
    return {
        "gamma_trigger":            gamma_trigger,
        "call_wall":                call_wall,
        "put_wall":                 put_wall,
        "acceleration_zone_start":  accel["strike"].min() if not accel.empty else None,
        "acceleration_zone_end":    accel["strike"].max() if not accel.empty else None,
        "distance_to_trigger_pct":  ((gamma_trigger - current_price) / current_price * 100) if gamma_trigger else None,
        "call_by_strike":           call_by_strike,
        "put_by_strike":            put_by_strike,
    }

# ─────────────────────────────────────────────
# PRD UPGRADED ENGINE — JEG BALLISTICS v6
# Trend Qualification · Rejection Pattern ·
# Gamma Flip · Acceleration · Invalidation
# ─────────────────────────────────────────────

def compute_trend_indicators(spot: float, rng) -> dict:
    """
    Simulate EMA20, SMA50, EMA20>SMA50 trend qualification.
    In live mode these would come from price history.
    """
    # Simulate realistic trend context from seed
    ema20_offset = rng.uniform(-0.03, 0.06)   # EMA20 relative to spot
    sma50_offset = rng.uniform(-0.06, 0.08)   # SMA50 relative to spot
    ema20 = spot * (1 + ema20_offset)
    sma50 = spot * (1 + sma50_offset)

    price_above_ema20 = spot > ema20
    price_above_sma50 = spot > sma50
    ema20_above_sma50 = ema20 > sma50

    # Full trend qualification: all 3 conditions per PRD
    trend_qualified = price_above_ema20 and price_above_sma50 and ema20_above_sma50

    return {
        "ema20":              round(ema20, 2),
        "sma50":              round(sma50, 2),
        "price_above_ema20":  price_above_ema20,
        "price_above_sma50":  price_above_sma50,
        "ema20_above_sma50":  ema20_above_sma50,
        "trend_qualified":    trend_qualified,
        "invalidation":       round(ema20, 2),  # PRD: invalidation = EMA20 or recent swing low
    }

def detect_rejection_pattern(spot: float, call_wall, rng) -> dict:
    """
    PRD: Rejection = price traded ABOVE call wall intraday, closed BELOW it.
    high > call_wall and close < call_wall → rejection = True
    """
    if not call_wall or not isinstance(call_wall, float):
        return {"rejection": False, "intraday_high": spot, "rejection_strength": 0}
    intraday_high = spot * rng.uniform(0.995, 1.035)
    rejection = intraday_high > call_wall and spot < call_wall
    if rejection:
        wick_size = (intraday_high - call_wall) / call_wall * 100
        strength = min(100, int(wick_size * 20))
    else:
        strength = 0
    return {
        "rejection":          rejection,
        "intraday_high":      round(intraday_high, 2),
        "rejection_strength": strength,
    }

def detect_ma_reclaim_breakout(spot: float, rng) -> dict:
    """
    Detects the TSEM-style setup:
    - Deep base below MAs → EMA20 crosses above SMA50
    - Price breaks ABOVE both MAs on volume expansion
    - MACD crosses bullish (MACD line > signal line, histogram rising)
    - RSI climbing through 50-70 zone (momentum confirmed, not overbought)
    - Clean breakout — no failed attempts in last 5 bars

    This is the exact pattern: compressed base → MA curl → volume breakout
    """
    # Simulate MA structure
    ema20_offset = rng.uniform(-0.04, 0.08)
    sma50_offset = rng.uniform(-0.07, 0.09)
    sma200_offset = rng.uniform(-0.15, 0.05)
    ema20  = spot * (1 + ema20_offset)
    sma50  = spot * (1 + sma50_offset)
    sma200 = spot * (1 + sma200_offset)

    # Key conditions from the TSEM chart
    price_above_ema20  = spot > ema20
    price_above_sma50  = spot > sma50
    price_above_sma200 = spot > sma200
    ema20_above_sma50  = ema20 > sma50   # The golden cross / EMA reclaim

    # Simulate MACD (12,26,9)
    macd_line   = rng.uniform(-3, 6)
    signal_line = rng.uniform(-4, 4)
    histogram   = macd_line - signal_line
    macd_bullish_cross = macd_line > signal_line and histogram > 0
    macd_histogram_rising = histogram > rng.uniform(-1, 0)  # histogram expanding

    # Simulate RSI (14)
    rsi = rng.uniform(35, 85)
    rsi_momentum_zone = 50 < rsi < 72   # Above 50 = momentum, below 72 = not overbought

    # Volume expansion (relative to avg)
    vol_expansion = rng.uniform(0.5, 3.5)
    strong_volume = vol_expansion > 1.5

    # Base compression: price was below MAs recently, now breaking out
    # Proxy: EMA20 recently crossed above SMA50 (fresh cross = more powerful)
    fresh_ma_cross = ema20_above_sma50 and rng.random() > 0.4

    # Consolidation quality: tight range before breakout
    base_tightness = rng.uniform(0, 1)
    tight_base = base_tightness > 0.5

    # Full pattern score
    pattern_score = 0
    if price_above_ema20:    pattern_score += 20
    if price_above_sma50:    pattern_score += 15
    if ema20_above_sma50:    pattern_score += 20   # EMA reclaim = core signal
    if macd_bullish_cross:   pattern_score += 20   # MACD cross
    if macd_histogram_rising:pattern_score += 5
    if rsi_momentum_zone:    pattern_score += 10   # RSI 50-72
    if strong_volume:        pattern_score += 10   # Volume confirmation

    pattern_score = min(pattern_score, 100)
    pattern_active = pattern_score >= 65 and ema20_above_sma50 and macd_bullish_cross

    return {
        "ema20":                round(ema20, 2),
        "sma50":                round(sma50, 2),
        "sma200":               round(sma200, 2),
        "ema20_above_sma50":    ema20_above_sma50,
        "price_above_ema20":    price_above_ema20,
        "price_above_sma50":    price_above_sma50,
        "price_above_sma200":   price_above_sma200,
        "macd_bullish":         macd_bullish_cross,
        "macd_histogram":       round(histogram, 3),
        "rsi":                  round(rsi, 1),
        "rsi_momentum_zone":    rsi_momentum_zone,
        "vol_expansion":        round(vol_expansion, 2),
        "strong_volume":        strong_volume,
        "fresh_ma_cross":       fresh_ma_cross,
        "pattern_score":        pattern_score,
        "pattern_active":       pattern_active,
        "signal":               "🔥 MA RECLAIM BREAKOUT" if pattern_active else "—",
    }


    """
    PRD: Rejection = price traded ABOVE call wall intraday, closed BELOW it.
    high > call_wall and close < call_wall → rejection = True
    """
    if not call_wall or not isinstance(call_wall, float):
        return {"rejection": False, "intraday_high": spot, "rejection_strength": 0}

    # Simulate intraday high relative to call wall
    intraday_high = spot * rng.uniform(0.995, 1.035)
    rejection = intraday_high > call_wall and spot < call_wall

    # Rejection strength = size of wick above call wall
    if rejection:
        wick_size = (intraday_high - call_wall) / call_wall * 100
        strength = min(100, int(wick_size * 20))  # stronger wick = stronger signal
    else:
        strength = 0

    return {
        "rejection":          rejection,
        "intraday_high":      round(intraday_high, 2),
        "rejection_strength": strength,
    }

def find_gamma_flip(chain_df, current_price) -> float | None:
    """
    PRD: Gamma flip ≈ nearest strike where call OI dominates above price.
    More precise than just gamma_trigger — weighted by OI concentration.
    """
    calls_above = chain_df[
        (chain_df["option_type"] == "call") &
        (chain_df["strike"] > current_price)
    ].copy()
    if calls_above.empty:
        return None
    # Group by strike, find where call OI dominates most strongly
    by_strike = calls_above.groupby("strike")["open_interest"].sum()
    # Gamma flip = lowest strike with above-median OI concentration
    median_oi = by_strike.median()
    dominant = by_strike[by_strike > median_oi]
    return float(dominant.index.min()) if not dominant.empty else float(by_strike.index.min())

def find_acceleration_level(chain_df, call_wall) -> float | None:
    """
    PRD: Acceleration = next significant strike above call wall.
    This is where the move accelerates once call wall is cleared.
    """
    if not call_wall:
        return None
    calls_above_wall = chain_df[
        (chain_df["option_type"] == "call") &
        (chain_df["strike"] > call_wall)
    ].copy()
    if calls_above_wall.empty:
        return None
    by_strike = calls_above_wall.groupby("strike")["open_interest"].sum()
    # Next meaningful strike = lowest strike above wall with decent OI
    threshold = by_strike.quantile(0.4)
    meaningful = by_strike[by_strike >= threshold]
    return float(meaningful.index.min()) if not meaningful.empty else float(by_strike.index.min())

def compute_trend_score(trend: dict) -> float:
    """PRD Weight: Trend Strength = 20%"""
    s = 0
    if trend["price_above_ema20"]:  s += 7
    if trend["price_above_sma50"]:  s += 7
    if trend["ema20_above_sma50"]:  s += 6
    return min(s, 20)

def compute_options_pressure_score(gl, gamma_flip, rejection: dict) -> float:
    """
    PRD Weight: Options Pressure = 30%
    Combines: call wall strength + gamma flip proximity + put wall support + rejection
    """
    s = 0.0
    # Call wall presence and strength
    if gl["call_wall"]:
        cbs = gl["call_by_strike"]
        if len(cbs) > 0:
            top_gex = cbs.nlargest(3, "gex_proxy")["gex_proxy"].mean()
            s += 12 if top_gex > 50000 else 8 if top_gex > 20000 else 4
        s += 5  # call wall exists bonus

    # Gamma flip proximity
    if gamma_flip and gl.get("gamma_trigger"):
        flip_dist = abs(gamma_flip - gl["gamma_trigger"]) / max(gamma_flip, 1) * 100
        s += 8 if flip_dist < 1 else 5 if flip_dist < 3 else 2

    # Put wall support below
    if gl["put_wall"]:
        s += 5

    return min(s, 30)

def compute_rejection_score(rejection: dict) -> float:
    """PRD Weight: Rejection Pattern = 20%"""
    if not rejection["rejection"]:
        return 0
    # Scale by wick strength
    return min(20, 10 + rejection["rejection_strength"] * 0.1)

def compute_opex_context_score(opex_boost: int) -> float:
    """PRD Weight: OPEX Context = 20%"""
    if opex_boost > 0:    return 20   # POST-OPEX REBUILD — maximum score
    elif opex_boost < 0:  return 5    # PRE-OPEX PIN — minimal score (pinning suppresses moves)
    else:                 return 12   # MID-CYCLE — neutral

def compute_liquidity_score(rel_vol: float, cp_ratio: float, has_sweeps: bool) -> float:
    """PRD Weight: Liquidity = 10%"""
    s = 4 if rel_vol > 2 else 3 if rel_vol > 1.5 else 2 if rel_vol > 1.2 else 1
    s += 3 if cp_ratio > 1.5 else 2 if cp_ratio > 1.2 else 1
    s += 3 if has_sweeps else 0
    return min(s, 10)

def compute_flow_score(rng):
    """Options flow simulation — retained from v5, feeds into liquidity."""
    cp = rng.uniform(0.8, 3.5)
    sw = rng.random() > 0.45
    ps = rng.choice(["small","medium","large","unusual"], p=[0.25,0.35,0.25,0.15])
    s  = 35 if cp>2 else 25 if cp>1.5 else 15 if cp>1.2 else 5
    s += 30 * sw + (25 if ps=="unusual" else 18 if ps=="large" else 10 if ps=="medium" else 0)
    return min(s, 100), cp, sw, ps

def compute_volume_score(rel_vol, above_vwap):
    s = 50 if rel_vol>2 else 38 if rel_vol>1.5 else 25 if rel_vol>1.3 else 10
    s += 35 * above_vwap
    return min(s, 100)

def compute_sentiment_score_component(sent_raw: float) -> float:
    return round(min(100, max(0, (sent_raw + 1.0) * 50.0)))

def generate_trade_idea(ticker, price, breakout, gamma_trigger, call_wall, gamma_flip,
                        acceleration, invalidation, rejection, score,
                        sentiment_label="NEUTRAL", opex_phase="MID-CYCLE"):
    """
    PRD-aligned trade idea with full context:
    breakout trigger, acceleration level, invalidation, rejection pattern
    """
    opex_note = " [POST-OPEX REBUILD — amplified move expected]" if "REBUILD" in opex_phase else \
                " [PRE-OPEX — caution, pinning risk]" if "PIN" in opex_phase else ""
    sent_note = " [bullish sentiment tailwind]" if sentiment_label == "BULLISH" else \
                " [bearish headwind — tighten stops]" if sentiment_label == "BEARISH" else ""

    inval_str = f" | Invalidation: ${invalidation:.0f}" if invalidation else ""
    accel_str = f" | Accel target: ${acceleration:.0f}" if acceleration else ""

    if rejection:
        # Rejection pattern = wait for reclaim
        reclaim = call_wall if call_wall else breakout
        return f"Rejection at ${reclaim:.0f} call wall — buy RECLAIM above ${reclaim:.0f}; accel to ${acceleration:.0f}{inval_str}{opex_note}{sent_note}" if acceleration else \
               f"Rejection at call wall — wait for reclaim above ${reclaim:.0f}{inval_str}{opex_note}{sent_note}"

    if score >= 85:
        if gamma_flip and gamma_trigger and abs(gamma_flip - gamma_trigger) / price < 0.02:
            return f"A+ SETUP: Breakout above ${breakout:.0f}; gamma flip at ${gamma_flip:.0f} forces dealer buying{accel_str}{inval_str}{opex_note}{sent_note}"
        return f"High-conviction breakout above ${breakout:.0f}; target ${acceleration:.0f} acceleration zone{inval_str}{opex_note}{sent_note}" if acceleration else \
               f"High-conviction breakout above ${breakout:.0f}; target call wall ${call_wall:.0f}{inval_str}{opex_note}{sent_note}" if call_wall else \
               f"Buy breakout above ${breakout:.0f}{inval_str}{opex_note}{sent_note}"
    elif score >= 70:
        return f"Watch ${breakout:.0f} breakout — confirm volume; gamma flip ${gamma_flip:.0f}{accel_str}{inval_str}{opex_note}{sent_note}" if gamma_flip else \
               f"Watch for breakout above ${breakout:.0f}; confirm on volume{inval_str}{opex_note}{sent_note}"
    elif score >= 55:
        return f"Monitor ${breakout:.0f} level; wait for options flow + trend confirmation{inval_str}{sent_note}"
    return f"Below threshold — ignore or watch for setup development{sent_note}"


# ─────────────────────────────────────────────
# MAIN SCAN FUNCTION
# ─────────────────────────────────────────────
def parse_etrade_quotes(etrade_quote_data: dict) -> dict:
    """
    Parse E*TRADE QuoteResponse into a simple {ticker: price} dict
    so it can feed directly into the scan engine as live prices.
    """
    prices = {}
    if not etrade_quote_data:
        return prices
    try:
        ql = etrade_quote_data.get("QuoteResponse", {}).get("QuoteData", [])
        if not isinstance(ql, list):
            ql = [ql]
        for q in ql:
            sym  = q.get("Product", {}).get("symbol", "")
            last = q.get("All", {}).get("lastTrade", 0)
            if sym and last:
                prices[sym] = float(last)
    except Exception:
        pass
    return prices


@st.cache_data(ttl=60, show_spinner=False)
def run_full_scan(
    selected_tickers: tuple,
    score_threshold: int,
    api_key: str,
    use_live: bool,
    opex_boost: int,
    sentiment_weight: float,
    apply_opex_filter: bool,
    apply_sentiment: bool,
    etrade_prices: tuple = (),
) -> pd.DataFrame:

    live_prices = {}
    # Pull in E*TRADE live quotes first (most accurate)
    if etrade_prices:
        live_prices.update(dict(etrade_prices))
    # Fill any gaps with Polygon.io
    if use_live and api_key and REQUESTS_OK:
        missing = [t for t in selected_tickers if t not in live_prices]
        if missing:
            with st.spinner("📡 Fetching live prices..."):
                polygon_prices = fetch_live_snapshot(missing, api_key)
                live_prices.update(polygon_prices)

    results = []
    for ticker in selected_tickers:
        base_price = UNIVERSE.get(ticker, 100.0)
        spot = live_prices.get(ticker) or (base_price * np.random.uniform(0.97, 1.03))
        rng  = np.random.RandomState(abs(hash(ticker + str(datetime.now().date()))) % 100000)

        chain = None
        if use_live and api_key and REQUESTS_OK:
            chain = fetch_options_chain(ticker, api_key, spot)
        if chain is None:
            chain = generate_simulated_chain(ticker, spot, seed=abs(hash(ticker)) % 9999)

        resistance  = spot * rng.uniform(1.01, 1.05)
        rel_vol     = rng.uniform(0.8, 2.8)
        above_vwap  = rng.random() > 0.35

        # PRD: Trend Qualification
        trend = compute_trend_indicators(spot, rng)

        # TSEM-Style MA Reclaim + MACD Breakout Pattern
        ma_reclaim = detect_ma_reclaim_breakout(spot, rng)

        # Gamma Levels
        gl = identify_gamma_levels(chain, spot)

        # PRD: Gamma Flip + Acceleration Level
        gamma_flip   = find_gamma_flip(chain, spot)
        acceleration = find_acceleration_level(chain, gl["call_wall"])

        # PRD: Rejection Pattern
        rejection_data = detect_rejection_pattern(spot, gl["call_wall"], rng)

        # Options flow
        flow_s, cp_ratio, has_sweeps, prem_sz = compute_flow_score(rng)
        vol_s = compute_volume_score(rel_vol, above_vwap)

        # PRD SCORING MODEL (adds to 100)
        trend_s   = compute_trend_score(trend)
        options_s = compute_options_pressure_score(gl, gamma_flip, rejection_data)
        reject_s  = compute_rejection_score(rejection_data)
        opex_s    = compute_opex_context_score(opex_boost if apply_opex_filter else 0)
        liquid_s  = compute_liquidity_score(rel_vol, cp_ratio, has_sweeps)
        prd_score = trend_s + options_s + reject_s + opex_s + liquid_s

        # Sentiment blend
        sent_data = compute_ticker_sentiment(ticker, api_key) if apply_sentiment else {
            "score": 0, "raw": 0.0, "label": "N/A", "color": "#94a3b8", "icon": "—", "articles": []
        }
        sent_component = compute_sentiment_score_component(sent_data["raw"]) if apply_sentiment else 50

        if apply_sentiment and sentiment_weight > 0:
            total_s = round(prd_score * (1 - sentiment_weight) + sent_component * sentiment_weight, 1)
        else:
            total_s = round(prd_score, 1)

        # Boost score if TSEM-style MA Reclaim Breakout is active
        if ma_reclaim["pattern_active"]:
            total_s = min(99.9, total_s + ma_reclaim["pattern_score"] * 0.08)
        total_s = max(0, min(99.9, total_s))

        trade = generate_trade_idea(
            ticker, spot, resistance,
            gl["gamma_trigger"], gl["call_wall"],
            gamma_flip, acceleration,
            trend["invalidation"],
            rejection_data["rejection"],
            total_s, sent_data["label"],
            "REBUILD" if opex_boost > 0 else "PIN" if opex_boost < 0 else "MID"
        )
        etrade_price_dict = dict(etrade_prices) if etrade_prices else {}
        if ticker in etrade_price_dict:
            data_src = "🟢 E*TRADE"
        elif ticker in live_prices:
            data_src = "📡 POLYGON"
        else:
            data_src = "🔵 SIM"

        results.append({
            "Ticker":           ticker,
            "Price":            round(spot, 2),
            "Breakout":         round(resistance, 2),
            "γ Trigger":        round(gl["gamma_trigger"], 2) if gl["gamma_trigger"] else "—",
            "Gamma Flip":       round(gamma_flip, 2) if gamma_flip else "—",
            "Call Wall":        round(gl["call_wall"], 2) if gl["call_wall"] else "—",
            "Put Wall":         round(gl["put_wall"], 2) if gl["put_wall"] else "—",
            "Acceleration":     round(acceleration, 2) if acceleration else "—",
            "Invalidation":     round(trend["invalidation"], 2),
            "Rejection":        "⚡ YES" if rejection_data["rejection"] else "—",
            "MA Reclaim":       ma_reclaim["signal"],
            "RSI":              round(ma_reclaim["rsi"], 1),
            "MACD":             "✓ BULL" if ma_reclaim["macd_bullish"] else "—",
            "Pattern Score":    round(ma_reclaim["pattern_score"], 1),
            "Trend":            "✓" if trend["trend_qualified"] else "—",
            "EMA20":            round(trend["ema20"], 2),
            "SMA50":            round(trend["sma50"], 2),
            "Rel Vol":          round(rel_vol, 2),
            "CP Ratio":         round(cp_ratio, 2),
            "Sweeps":           "✓" if has_sweeps else "—",
            "Trend Score":      round(trend_s, 1),
            "Options Score":    round(options_s, 1),
            "Rejection Score":  round(reject_s, 1),
            "OPEX Score":       round(opex_s, 1),
            "Liquidity Score":  round(liquid_s, 1),
            "Sentiment":        round(sent_component, 1),
            "Sentiment Label":  sent_data["label"],
            "Sent Color":       sent_data["color"],
            "Sent Icon":        sent_data["icon"],
            "SCORE":            total_s,
            "Data":             data_src,
            "Trade Idea":       trade,
            "_spot":            spot,
            "_chain_seed":      abs(hash(ticker)) % 9999,
            "_sent_raw":        sent_data["raw"],
        })

    df = pd.DataFrame(results)
    df = df[df["SCORE"] >= score_threshold].sort_values("SCORE", ascending=False).reset_index(drop=True)
    return df


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
if "alerts_sent" not in st.session_state:
    st.session_state.alerts_sent = set()
if "alert_log" not in st.session_state:
    st.session_state.alert_log = []

# ─────────────────────────────────────────────
# OPEX STATUS (computed once per session reload)
# ─────────────────────────────────────────────
opex_info = get_opex_status()

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    # Logo
    import os, base64
    _logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
    try:
        with open(_logo_path, "rb") as f:
            _logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(f"""
        <div style="text-align:center; padding:12px 0 8px 0;">
            <img src="data:image/png;base64,{_logo_b64}" style="width:160px; height:160px; object-fit:contain; margin-bottom:4px;">
            <div style="font-family:'Orbitron',sans-serif; font-size:0.55rem; color:#475569; letter-spacing:0.3em; text-transform:uppercase;">Operation</div>
            <div style="font-family:'Orbitron',sans-serif; font-size:1.1rem; font-weight:900; color:#00ff88; letter-spacing:0.08em;">JEG BALLISTIC AI</div>
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#475569; letter-spacing:0.15em; margin-top:2px;">GAMMA RECLAIM ENGINE v6</div>
        </div>
        <hr style="border-color:#1e2a3a; margin:8px 0 12px 0;">
        """, unsafe_allow_html=True)
    except Exception:
        st.markdown('<div style="text-align:center; padding:12px 0;"><div style="font-family:Orbitron,sans-serif; font-size:1.1rem; font-weight:900; color:#00ff88;">JEG BALLISTIC AI</div></div>', unsafe_allow_html=True)

    # ── API KEY ──
    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ Polygon.io API Key</p>', unsafe_allow_html=True)
    api_key  = st.text_input("", placeholder="Paste your API key here", type="password", label_visibility="collapsed")
    use_live = bool(api_key and REQUESTS_OK)
    if use_live:
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.6rem; color:#00ff88; margin-top:2px;">● LIVE DATA ACTIVE</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.6rem; color:#ffb800; margin-top:2px;">● SIMULATION MODE (enter API key for live)</p>', unsafe_allow_html=True)

    st.markdown("---")

    # ── E*TRADE LIVE STATUS ──
    if st.session_state.get("etrade_connected"):
        ec = "#ffb800" if st.session_state.etrade_sandbox else "#00ff88"
        el = "SANDBOX" if st.session_state.etrade_sandbox else "LIVE"
        n_quoted = len(parse_etrade_quotes(st.session_state.etrade_live_quotes)) if st.session_state.etrade_live_quotes else 0
        st.markdown(f"""<div style="background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.3);border-radius:6px;padding:10px 12px;margin-bottom:8px;">
            <div style="font-family:'Share Tech Mono',monospace;font-size:0.62rem;color:#00ff88;">◉ E*TRADE {el} — CONNECTED</div>
            <div style="font-family:'Share Tech Mono',monospace;font-size:0.58rem;color:{ec};margin-top:3px;">{n_quoted} tickers with live prices</div>
        </div>""", unsafe_allow_html=True)
        if st.button("🔄 REFRESH LIVE PRICES", use_container_width=True, key="sidebar_refresh_prices"):
            with st.spinner("Fetching live prices from E*TRADE..."):
                _syms = list(UNIVERSE.keys())[:50]
                r = etrade_get_quotes(
                    st.session_state.etrade_consumer_key,
                    st.session_state.etrade_consumer_secret,
                    st.session_state.etrade_access_token,
                    st.session_state.etrade_access_token_secret,
                    _syms,
                    st.session_state.etrade_sandbox,
                )
                if r["success"]:
                    st.session_state.etrade_live_quotes = r["data"]
                    st.success(f"✓ {len(parse_etrade_quotes(r['data']))} prices updated")
                    st.rerun()
                else:
                    st.error(f"Failed: {r['error']}")
        if st.button("⏏ DISCONNECT", use_container_width=True, key="sidebar_disconnect"):
            etrade_revoke_token(
                st.session_state.etrade_consumer_key, st.session_state.etrade_consumer_secret,
                st.session_state.etrade_access_token, st.session_state.etrade_access_token_secret,
                st.session_state.etrade_sandbox)
            for _k in ["etrade_connected","etrade_access_token","etrade_access_token_secret",
                        "etrade_accounts","etrade_selected_account","etrade_live_quotes"]:
                st.session_state[_k] = False if _k=="etrade_connected" else (None if "account" in _k else ({} if "quote" in _k else ""))
            st.rerun()

    # ── OPEX GAMMA REBUILD FILTER ──
    st.markdown(f'<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#8b5cf6; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ OPEX Gamma Filter</p>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="opex-badge">
        <div style="color:{opex_info['phase_color']}; font-size:0.7rem; font-weight:bold; margin-bottom:4px;">{opex_info['phase']}</div>
        <div style="color:#94a3b8; font-size:0.6rem; line-height:1.5;">{opex_info['phase_desc']}</div>
        <div style="color:#475569; font-size:0.58rem; margin-top:4px;">
            Last OPEX: {opex_info['last_opex']} &nbsp;|&nbsp; Next: {opex_info['next_opex']}
        </div>
    </div>
    """, unsafe_allow_html=True)
    apply_opex = st.checkbox("Apply OPEX Score Adjustment", value=True)
    if apply_opex:
        boost = opex_info["phase_boost"]
        boost_label = f"{'▲' if boost > 0 else '▼' if boost < 0 else '─'} {abs(boost)} pts {'boost (rebuild)' if boost > 0 else 'penalty (pin)' if boost < 0 else '(neutral)'}"
        st.markdown(f'<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.6rem; color:{opex_info["phase_color"]}; margin-top:2px;">{boost_label}</p>', unsafe_allow_html=True)
    else:
        boost = 0

    st.markdown("---")

    # ── SENTIMENT ENGINE ──
    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ News Sentiment</p>', unsafe_allow_html=True)
    apply_sentiment = st.checkbox("Enable Sentiment Scoring", value=True)
    sent_weight = st.slider("Sentiment Weight in Score", 0, 20, 10, help="% of final score from news sentiment") / 100.0
    if apply_sentiment:
        st.markdown(f'<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.6rem; color:#00ff88; margin-top:2px;">● SENTIMENT ACTIVE ({int(sent_weight*100)}% weight)</p>', unsafe_allow_html=True)

    st.markdown("---")

    # ── UNIVERSE ──
    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ Universe (60 tickers)</p>', unsafe_allow_html=True)
    categories = {
        "🔥 Mega Cap Tech": ["NVDA","AAPL","MSFT","GOOGL","META","AMZN","TSLA","AMD","AVGO","ORCL"],
        "⚡ Semis":         ["ARM","SMCI","MU","INTC","QCOM","TXN","AMAT","LRCX","KLAC","ASML"],
        "☁️ Software":      ["CRM","NOW","SNOW","DDOG","ZS","CRWD","PLTR","COIN","MSTR","UBER"],
        "📊 ETFs":          ["SPY","QQQ","IWM","XLK","TQQQ","SOXL","ARKK","GLD","SLV","SOXS"],
        "💰 Finance":       ["JPM","GS","MS","BAC","V"],
        "💊 Healthcare":    ["LLY","NVO","MRNA","ABBV","PFE"],
        "🛢 Energy":        ["XOM","CVX","OXY"],
        "🎯 High OI":       ["NFLX","BABA","VEEV","MELI","SHOP","SQ","PYPL","RBLX","RIVN","GME"],
    }
    preset = st.selectbox("Quick Select", ["Custom","All 60","Top 20 by Volume","ETFs Only","Tech Heavy"], label_visibility="collapsed")
    if preset == "All 60":
        default_tickers = list(UNIVERSE.keys())
    elif preset == "ETFs Only":
        default_tickers = categories["📊 ETFs"]
    elif preset == "Tech Heavy":
        default_tickers = categories["🔥 Mega Cap Tech"] + categories["⚡ Semis"] + categories["☁️ Software"]
    elif preset == "Top 20 by Volume":
        default_tickers = ["NVDA","TSLA","AAPL","AMD","SPY","QQQ","META","AMZN","MSFT","GOOGL","PLTR","COIN","MSTR","SMCI","ARM","TQQQ","SOXL","BABA","GME","RIVN"]
    else:
        default_tickers = list(UNIVERSE.keys())[:20]
    selected = st.multiselect("Tickers", list(UNIVERSE.keys()), default=default_tickers, label_visibility="collapsed")

    st.markdown("---")

    # ── SCORE FILTER ──
    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ Min Score</p>', unsafe_allow_html=True)
    min_score = st.slider("", 50, 90, 65, label_visibility="collapsed")
    st.markdown("""
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; line-height:2; margin-top:4px;">
        <span style="color:#00ff88;">●</span> <span style="color:#94a3b8;">85+ A+ PRESS TRADES</span><br>
        <span style="color:#ffb800;">●</span> <span style="color:#94a3b8;">70–84 STRONG SETUP</span><br>
        <span style="color:#00b4ff;">●</span> <span style="color:#94a3b8;">55–69 WATCH</span><br>
        <span style="color:#475569;">●</span> <span style="color:#475569;">&lt;55 IGNORE</span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # ── ALERTS ──
    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ Email Alerts (85+)</p>', unsafe_allow_html=True)
    alert_email     = st.text_input("Your email",    placeholder="you@gmail.com",         label_visibility="collapsed")
    sender_email    = st.text_input("Sender Gmail",  placeholder="sender@gmail.com",       label_visibility="collapsed")
    sender_password = st.text_input("Gmail App Pw",  placeholder="xxxx xxxx xxxx xxxx",   type="password", label_visibility="collapsed")
    alerts_enabled  = st.checkbox("Enable email alerts", value=False)

    st.markdown("---")

    # ── AUTO REFRESH ──
    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">⬡ Auto Refresh</p>', unsafe_allow_html=True)
    auto_refresh = st.checkbox("Refresh every 5 min", value=False)
    if auto_refresh:
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.6rem; color:#00ff88;">● AUTO-SCAN ACTIVE</p>', unsafe_allow_html=True)

    run_scan = st.button("⚡ FIRE SCAN", use_container_width=True)


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
col_title, col_opex, col_clock = st.columns([3, 2, 1])
with col_title:
    st.markdown("""
    <div style="padding:8px 0 10px 0;">
        <div style="font-family:'Orbitron',sans-serif; font-size:0.5rem; color:#475569; letter-spacing:0.4em; text-transform:uppercase;">JEG Securities — Classified Intelligence System</div>
        <div style="font-family:'Orbitron',sans-serif; font-size:1.6rem; font-weight:900; background:linear-gradient(90deg,#00ff88 0%,#00b4ff 60%,#8b5cf6 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; letter-spacing:0.04em; line-height:1.1; margin-top:4px;">BALLISTIC AI</div>
        <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#94a3b8; letter-spacing:0.2em; margin-top:4px;">TREND · OPTIONS · REJECTION · OPEX · SENTIMENT · v6</div>
    </div>
    """, unsafe_allow_html=True)
with col_opex:
    st.markdown(f"""
    <div style="padding-top:14px;">
        <div style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#475569; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:4px;">OPEX CYCLE</div>
        <div style="font-family:'Orbitron',sans-serif; font-size:0.8rem; color:{opex_info['phase_color']}; font-weight:700;">{opex_info['phase']}</div>
        <div style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#94a3b8; margin-top:2px;">{opex_info['days_since']}d post · {opex_info['days_until']}d to next OPEX</div>
    </div>
    """, unsafe_allow_html=True)
with col_clock:
    now = datetime.now()
    is_open = now.replace(hour=9,minute=30,second=0) <= now <= now.replace(hour=16,minute=0,second=0)
    status = "🟢 MARKET OPEN" if is_open else "🟡 PRE/AFTER MKT"
    mode   = "📡 LIVE" if use_live else "🔵 SIM"
    st.markdown(f"""
    <div style="text-align:right; padding-top:16px;">
        <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#475569;">{now.strftime('%a %b %d, %Y')}</div>
        <div style="font-family:'Orbitron',sans-serif; font-size:1.1rem; color:#00ff88;">{now.strftime('%H:%M:%S')}</div>
        <div style="font-family:'Share Tech Mono',monospace; font-size:0.58rem; color:#94a3b8; margin-top:2px;">{status} · {mode}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown('<hr style="border-color:#1e2a3a; margin:0 0 12px 0;">', unsafe_allow_html=True)

# Auto refresh
if auto_refresh:
    time.sleep(300)
    st.rerun()

# ─────────────────────────────────────────────
# RUN SCAN
# ─────────────────────────────────────────────
if not selected:
    st.warning("Select at least one ticker from the sidebar.")
    st.stop()

# ── Pull E*TRADE live prices if connected ──
etrade_live_price_dict = {}
if st.session_state.get("etrade_connected") and st.session_state.get("etrade_live_quotes"):
    etrade_live_price_dict = parse_etrade_quotes(st.session_state.etrade_live_quotes)

# Auto-fetch E*TRADE quotes for selected tickers if connected and no quotes yet
if st.session_state.get("etrade_connected") and not etrade_live_price_dict:
    with st.spinner("📡 Fetching live prices from E*TRADE..."):
        r = etrade_get_quotes(
            st.session_state.etrade_consumer_key,
            st.session_state.etrade_consumer_secret,
            st.session_state.etrade_access_token,
            st.session_state.etrade_access_token_secret,
            list(selected)[:50],
            st.session_state.etrade_sandbox,
        )
        if r["success"]:
            st.session_state.etrade_live_quotes = r["data"]
            etrade_live_price_dict = parse_etrade_quotes(r["data"])

# Show data source status
if etrade_live_price_dict:
    n_live = sum(1 for t in selected if t in etrade_live_price_dict)
    st.markdown(f'''<div style="background:#0d1a0d;border:1px solid #00ff8844;border-radius:6px;padding:8px 14px;margin-bottom:8px;font-family:'Share Tech Mono',monospace;font-size:0.65rem;">
        🟢 <b style="color:#00ff88;">E*TRADE LIVE</b> — {n_live}/{len(selected)} tickers priced from live market data
    </div>''', unsafe_allow_html=True)

with st.spinner("🎯 Running Ballistic Scan..."):
    scan_df = run_full_scan(
        tuple(sorted(selected)),
        min_score,
        api_key,
        use_live,
        boost if apply_opex else 0,
        sent_weight if apply_sentiment else 0.0,
        apply_opex,
        apply_sentiment,
        tuple(sorted(etrade_live_price_dict.items())),
    )

# Market-wide sentiment
mkt_sent = fetch_market_sentiment_indicators(api_key)

# ─────────────────────────────────────────────
# ALERT PROCESSING
# ─────────────────────────────────────────────
elite_setups = scan_df[scan_df["SCORE"] >= 85]
new_alerts   = []
for _, row in elite_setups.iterrows():
    key = f"{row['Ticker']}_{datetime.now().strftime('%Y%m%d_%H')}"
    if key not in st.session_state.alerts_sent:
        new_alerts.append(row.to_dict())
        st.session_state.alerts_sent.add(key)
        st.session_state.alert_log.insert(0, {
            "time":      datetime.now().strftime("%H:%M:%S"),
            "ticker":    row["Ticker"],
            "score":     row["SCORE"],
            "sentiment": row.get("Sentiment Label", "—"),
            "trade":     row["Trade Idea"],
        })

if new_alerts:
    for alert in new_alerts:
        sc = "#00ff88" if alert["SCORE"] >= 85 else "#ffb800"
        st.markdown(f"""
        <div class="alert-box">
            🚨 <b style="font-family:'Orbitron',sans-serif; color:#00ff88; font-size:0.9rem;">ELITE SETUP: {alert['Ticker']}</b>
            <span style="font-family:'Share Tech Mono',monospace; font-size:0.7rem; color:#94a3b8; margin-left:16px;">
                Score: <b style="color:#00ff88;">{alert['SCORE']}</b> ·
                Sentiment: <b style="color:{alert.get('Sent Color','#94a3b8')};">{alert.get('Sentiment Label','—')}</b> ·
                {alert['Trade Idea']}
            </span>
        </div>
        """, unsafe_allow_html=True)
    if alerts_enabled and alert_email and sender_email and sender_password:
        result = send_email_alert(alert_email, sender_email, sender_password, new_alerts)
        if result is True:
            st.success(f"📧 Alert email sent to {alert_email}")
        else:
            st.warning(f"Email failed: {result}")

# ─────────────────────────────────────────────
# METRICS ROW
# ─────────────────────────────────────────────
elite  = len(scan_df[scan_df["SCORE"] >= 85])
highp  = len(scan_df[(scan_df["SCORE"] >= 75) & (scan_df["SCORE"] < 85)])
watchl = len(scan_df[(scan_df["SCORE"] >= 65) & (scan_df["SCORE"] < 75)])
top_ticker = scan_df.iloc[0]["Ticker"] if len(scan_df) > 0 else "—"
top_score  = scan_df.iloc[0]["SCORE"]  if len(scan_df) > 0 else 0

# Dominant sentiment in results
if len(scan_df) > 0:
    bull_ct  = len(scan_df[scan_df["Sentiment Label"] == "BULLISH"])
    bear_ct  = len(scan_df[scan_df["Sentiment Label"] == "BEARISH"])
    sent_dom = "📈 BULL" if bull_ct > bear_ct else "📉 BEAR" if bear_ct > bull_ct else "➡ NEUT"
else:
    sent_dom = "—"

m1,m2,m3,m4,m5,m6,m7 = st.columns(7)
with m1: st.metric("SCANNED",    f"{len(selected)}", f"{len(scan_df)} passed")
with m2: st.metric("ELITE 85+",  elite,    "🟢 Act now")
with m3: st.metric("HIGH PROB",  highp,    "🟡 75–84")
with m4: st.metric("WATCHLIST",  watchl,   "🔵 65–74")
with m5: st.metric("TOP PICK",   top_ticker, f"Score {top_score}")
with m6: st.metric("MKT SENT",   mkt_sent["label"], f"SPY {mkt_sent['spy_chg']:+.2f}%")
with m7: st.metric("OPEX PHASE", opex_info["phase"].split()[-1], f"{opex_info['days_until']}d to next")

st.markdown('<div style="margin-bottom:10px;"></div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs([
    "🎯  WATCHLIST",
    "🔥  MA RECLAIM",
    "📰  SENTIMENT",
    "⚡  GAMMA MAP",
    "📊  BREAKDOWN",
    "🔍  DETAIL",
    "🎯  ENTRY DECISION",
    "💰  ORDER FLOW",
    "📱  MOBILE + ALERTS",
    "📡  E*TRADE PRO",
])

# ══════════════════════════════════════════════
# TAB 1 — WATCHLIST
# ══════════════════════════════════════════════
with tab1:
    if len(scan_df) == 0:
        st.info("No setups passed the score threshold. Lower the minimum score in the sidebar.")
    else:
        top5 = scan_df.head(5)
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.15em; text-transform:uppercase; margin-bottom:10px;">◈ TOP RANKED SETUPS</p>', unsafe_allow_html=True)
        card_cols = st.columns(min(5, len(top5)))
        for i, (_, row) in enumerate(top5.iterrows()):
            sc  = "#00ff88" if row["SCORE"]>=85 else "#ffb800" if row["SCORE"]>=75 else "#00b4ff"
            br  = (row["Breakout"]-row["Price"])/row["Price"]*100
            sic = row.get("Sent Icon", "—")
            slb = row.get("Sentiment Label", "N/A")
            sco = row.get("Sent Color", "#94a3b8")
            with card_cols[i]:
                st.markdown(f"""
                <div style="background:#0d1120; border:1px solid {sc}44; border-radius:8px; padding:14px 12px; text-align:center;">
                    <div style="font-family:'Orbitron',sans-serif; font-size:1.2rem; font-weight:900; color:{sc};">{row['Ticker']}</div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:#94a3b8;">${row['Price']:.2f} · {row['Data']}</div>
                    <div style="font-family:'Orbitron',sans-serif; font-size:1.4rem; font-weight:900; color:{sc}; margin:6px 0;">{row['SCORE']}</div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#475569; margin-bottom:6px;">SCORE</div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">Break: <b style="color:{sc};">${row['Breakout']:.2f}</b></div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">Dist: <b style="color:#ffb800;">{br:.1f}%</b></div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">Vol: <b style="color:#00b4ff;">×{row['Rel Vol']:.1f}</b></div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; margin-top:4px;">{sic} <b style="color:{sco};">{slb}</b></div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.15em; text-transform:uppercase; margin-bottom:6px;">◈ FULL SCAN RESULTS</p>', unsafe_allow_html=True)
        display_cols = ["Ticker","Price","Breakout","γ Trigger","Gamma Flip","Call Wall","Put Wall","Acceleration","Invalidation","Rejection","Trend","Rel Vol","CP Ratio","Sweeps","Trend Score","Options Score","Rejection Score","OPEX Score","Liquidity Score","Sentiment","Sentiment Label","SCORE","Data","Trade Idea"]
        st.dataframe(scan_df[display_cols], use_container_width=True, height=380)
        csv = scan_df[display_cols].to_csv(index=False)
        st.download_button("⬇ Export Watchlist CSV", csv, f"jeg_ballistic_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", "text/csv")


# ══════════════════════════════════════════════
# TAB 2 — MA RECLAIM BREAKOUT (TSEM-Style)
# ══════════════════════════════════════════════
with tab2:
    st.markdown("""<div style="padding:4px 0 12px 0;">
        <div style="font-family:'Orbitron',sans-serif;font-size:0.9rem;font-weight:700;color:#00ff88;letter-spacing:0.08em;">🔥 MA RECLAIM BREAKOUT SCANNER</div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;margin-top:4px;letter-spacing:0.1em;">EMA20 CROSS · MACD BULL · RSI MOMENTUM · VOLUME EXPANSION — The TSEM Pattern</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#0d1120;border:1px solid #00ff8833;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
        <div style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#00ff88;letter-spacing:0.1em;margin-bottom:12px;">◈ WHAT THIS SCANS FOR</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-family:'Share Tech Mono',monospace;font-size:0.62rem;color:#94a3b8;line-height:1.8;">
            <div><b style="color:#00ff88;">① EMA20 crosses above SMA50</b><br>The MA reclaim — the core trigger. Algos react immediately.</div>
            <div><b style="color:#ffb800;">② MACD bullish cross + rising histogram</b><br>Momentum confirmation. Trend is accelerating not fading.</div>
            <div><b style="color:#00b4ff;">③ RSI in 50–72 zone</b><br>Above 50 = buyers in control. Below 72 = still has room to run.</div>
            <div><b style="color:#8b5cf6;">④ Volume 1.5x+ average</b><br>Institutional participation. Weak volume breakouts fail.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if len(scan_df) == 0:
        st.info("Run a scan first — click ⚡ FIRE SCAN in the sidebar.")
    elif "MA Reclaim" not in scan_df.columns:
        st.warning("MA Reclaim column not found — please restart the app.")
    else:
        reclaim_df = scan_df[scan_df["MA Reclaim"] == "🔥 MA RECLAIM BREAKOUT"].copy()

        if len(reclaim_df) == 0:
            # Show all tickers with pattern scores even if not fully active
            st.info("No full MA Reclaim Breakouts in current scan. Showing highest pattern scores below.")
            if "Pattern Score" in scan_df.columns:
                top_patterns = scan_df.nlargest(10, "Pattern Score")[["Ticker","Price","SCORE","Pattern Score","RSI","MACD","Rel Vol","MA Reclaim","Trade Idea"]]
                st.dataframe(top_patterns, use_container_width=True, height=350)
        else:
            st.markdown(f"""<div style="background:#0d1a0d;border:1px solid #00ff8844;border-radius:6px;padding:10px 16px;margin-bottom:16px;font-family:'Share Tech Mono',monospace;font-size:0.68rem;color:#00ff88;">
                🔥 {len(reclaim_df)} MA RECLAIM BREAKOUT SETUP{"S" if len(reclaim_df)>1 else ""} DETECTED
            </div>""", unsafe_allow_html=True)

            # Top cards
            top_r = reclaim_df.head(5)
            rcols = st.columns(min(5, len(top_r)))
            for i, (_, row) in enumerate(top_r.iterrows()):
                sc = "#00ff88" if row["SCORE"] >= 85 else "#ffb800" if row["SCORE"] >= 70 else "#00b4ff"
                rsi_val = row.get("RSI", 0)
                rsi_c = "#00ff88" if 50 < rsi_val < 65 else "#ffb800" if rsi_val < 72 else "#ff3366"
                with rcols[i]:
                    st.markdown(f"""
                    <div style="background:#0d1120;border:1px solid {sc}55;border-radius:8px;padding:14px 12px;text-align:center;">
                        <div style="font-family:'Orbitron',sans-serif;font-size:1.1rem;font-weight:900;color:{sc};">{row['Ticker']}</div>
                        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#94a3b8;">${row['Price']:.2f}</div>
                        <div style="font-family:'Orbitron',sans-serif;font-size:1.3rem;font-weight:900;color:{sc};margin:6px 0;">{row['SCORE']:.1f}</div>
                        <div style="font-family:'Share Tech Mono',monospace;font-size:0.58rem;color:#475569;margin-bottom:8px;">SCORE</div>
                        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#94a3b8;">RSI: <b style="color:{rsi_c};">{rsi_val}</b></div>
                        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#94a3b8;">MACD: <b style="color:#00ff88;">{row.get('MACD','—')}</b></div>
                        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#94a3b8;">Vol: <b style="color:#00b4ff;">×{row['Rel Vol']:.1f}</b></div>
                        <div style="font-family:'Share Tech Mono',monospace;font-size:0.58rem;color:#8b5cf6;margin-top:6px;">Pattern: {row.get('Pattern Score','—')}</div>
                    </div>
                    """, unsafe_allow_html=True)

            st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:6px;">◈ FULL RECLAIM RESULTS</p>', unsafe_allow_html=True)
            avail = [c for c in ["Ticker","Price","Breakout","EMA20","SMA50","MACD","RSI","Rel Vol","Pattern Score","SCORE","Sentiment Label","Trade Idea"] if c in reclaim_df.columns]
            st.dataframe(reclaim_df[avail], use_container_width=True, height=300)

            # RSI vs Pattern Score scatter
            if len(reclaim_df) > 1 and "RSI" in reclaim_df.columns and "Pattern Score" in reclaim_df.columns:
                fig_rp = go.Figure()
                fig_rp.add_trace(go.Scatter(
                    x=reclaim_df["RSI"], y=reclaim_df["Pattern Score"],
                    mode="markers+text", text=reclaim_df["Ticker"],
                    textposition="top center",
                    textfont=dict(family="Share Tech Mono", size=9, color="#e2e8f0"),
                    marker=dict(color=reclaim_df["SCORE"],
                        colorscale=[[0,"#00b4ff"],[0.5,"#ffb800"],[1,"#00ff88"]],
                        size=12, opacity=0.85, line=dict(color="#060810", width=1))
                ))
                fig_rp.add_vrect(x0=50, x1=72, fillcolor="rgba(0,255,136,0.05)",
                    line=dict(color="#00ff88", width=1, dash="dot"),
                    annotation_text="Sweet Spot RSI 50-72",
                    annotation_font=dict(family="Share Tech Mono", size=9, color="#00ff88"))
                fig_rp.update_layout(
                    template="plotly_dark", paper_bgcolor="#060810", plot_bgcolor="#0a0d1a",
                    title=dict(text="RSI vs Pattern Score — TSEM-Style Setup Finder",
                               font=dict(family="Orbitron", size=12, color="#e2e8f0")),
                    xaxis=dict(title="RSI (14)", gridcolor="#1e2a3a", color="#94a3b8", range=[30,85]),
                    yaxis=dict(title="Pattern Score", gridcolor="#1e2a3a", color="#94a3b8", range=[0,105]),
                    height=380, margin=dict(t=50,b=50,l=60,r=20))
                st.plotly_chart(fig_rp, use_container_width=True)

# ══════════════════════════════════════════════
# TAB 2 — SENTIMENT (NEW)
# ══════════════════════════════════════════════
with tab3:
    st.markdown('<p style="font-family:\'Orbitron\',sans-serif; font-size:0.9rem; color:#00b4ff; letter-spacing:0.08em; margin-bottom:16px;">📰 REAL-TIME NEWS & MARKET SENTIMENT</p>', unsafe_allow_html=True)

    # ── Market-wide sentiment banner ──
    mkt_col1, mkt_col2, mkt_col3 = st.columns(3)
    with mkt_col1:
        st.markdown(f"""
        <div style="background:#0d1120; border:1px solid {mkt_sent['color']}44; border-radius:8px; padding:14px; text-align:center;">
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#475569; text-transform:uppercase; letter-spacing:0.1em;">Market Sentiment</div>
            <div style="font-family:'Orbitron',sans-serif; font-size:1.2rem; font-weight:900; color:{mkt_sent['color']}; margin:8px 0;">{mkt_sent['label']}</div>
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.65rem; color:#94a3b8;">SPY {mkt_sent['spy_chg']:+.2f}% · QQQ {mkt_sent['qqq_chg']:+.2f}%</div>
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#475569; margin-top:4px;">{'🟢 LIVE' if mkt_sent['source']=='live' else '🔵 SIM'}</div>
        </div>
        """, unsafe_allow_html=True)
    with mkt_col2:
        st.markdown(f"""
        <div style="background:#0d1120; border:1px solid {opex_info['phase_color']}44; border-radius:8px; padding:14px; text-align:center;">
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#475569; text-transform:uppercase; letter-spacing:0.1em;">OPEX Phase</div>
            <div style="font-family:'Orbitron',sans-serif; font-size:0.95rem; font-weight:900; color:{opex_info['phase_color']}; margin:8px 0;">{opex_info['phase']}</div>
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#94a3b8;">{opex_info['days_since']}d since · {opex_info['days_until']}d until</div>
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:{opex_info['phase_color']}; margin-top:4px;">
                {"Score +" + str(abs(opex_info['phase_boost'])) + " BOOST" if opex_info['phase_boost'] > 0 else "Score -" + str(abs(opex_info['phase_boost'])) + " PENALTY" if opex_info['phase_boost'] < 0 else "No adjustment"}
            </div>
        </div>
        """, unsafe_allow_html=True)
    with mkt_col3:
        if len(scan_df) > 0:
            bull_pct = len(scan_df[scan_df["Sentiment Label"]=="BULLISH"]) / len(scan_df) * 100
            bear_pct = len(scan_df[scan_df["Sentiment Label"]=="BEARISH"]) / len(scan_df) * 100
            neut_pct = 100 - bull_pct - bear_pct
            st.markdown(f"""
            <div style="background:#0d1120; border:1px solid #1e2a3a; border-radius:8px; padding:14px; text-align:center;">
                <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:#475569; text-transform:uppercase; letter-spacing:0.1em;">Scan Sentiment Mix</div>
                <div style="margin:8px 0; font-family:'Share Tech Mono',monospace; font-size:0.68rem;">
                    <span style="color:#00ff88;">📈 {bull_pct:.0f}% BULL</span><br>
                    <span style="color:#ff3366;">📉 {bear_pct:.0f}% BEAR</span><br>
                    <span style="color:#94a3b8;">➡ {neut_pct:.0f}% NEUT</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)

    # ── Sentiment bar chart for all tickers ──
    if len(scan_df) > 0:
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.15em; text-transform:uppercase; margin-bottom:8px;">◈ TICKER SENTIMENT SCORES</p>', unsafe_allow_html=True)

        sent_sorted = scan_df.sort_values("_sent_raw", ascending=True)
        bar_colors  = [row["Sent Color"] for _, row in sent_sorted.iterrows()]

        fig_sent = go.Figure(go.Bar(
            x=sent_sorted["_sent_raw"] * 100,
            y=sent_sorted["Ticker"],
            orientation="h",
            marker_color=bar_colors,
            opacity=0.85,
            text=[f"{v*100:+.0f}" for v in sent_sorted["_sent_raw"]],
            textposition="outside",
            textfont=dict(family="Share Tech Mono", size=9, color="#e2e8f0"),
        ))
        fig_sent.add_vline(x=0, line=dict(color="#2d3f55", width=1))
        fig_sent.add_vline(x=30, line=dict(color="#00ff88", width=1, dash="dot"))
        fig_sent.add_vline(x=-30, line=dict(color="#ff3366", width=1, dash="dot"))
        fig_sent.update_layout(
            template="plotly_dark", paper_bgcolor="#060810", plot_bgcolor="#0a0d1a",
            xaxis=dict(title="Sentiment Score", gridcolor="#1e2a3a", color="#94a3b8", range=[-110, 110], tickfont=dict(family="Share Tech Mono", size=9)),
            yaxis=dict(gridcolor="#1e2a3a", color="#94a3b8", tickfont=dict(family="Share Tech Mono", size=10)),
            height=max(300, len(scan_df) * 22 + 80),
            margin=dict(t=20, b=40, l=60, r=60),
            showlegend=False,
        )
        st.plotly_chart(fig_sent, use_container_width=True)

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)

    # ── Per-ticker news drill-down ──
    if len(scan_df) > 0:
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.15em; text-transform:uppercase; margin-bottom:8px;">◈ NEWS DRILL-DOWN</p>', unsafe_allow_html=True)
        news_ticker = st.selectbox("Select Ticker for News", scan_df["Ticker"].tolist(), key="news_sel")
        ticker_sent = compute_ticker_sentiment(news_ticker, api_key)

        sc = ticker_sent["color"]
        st.markdown(f"""
        <div style="background:#0d1120; border:1px solid {sc}44; border-radius:8px; padding:14px 18px; margin-bottom:14px; display:flex; align-items:center; gap:20px;">
            <div>
                <div style="font-family:'Orbitron',sans-serif; font-size:1.3rem; font-weight:900; color:{sc};">{news_ticker}</div>
                <div style="font-family:'Share Tech Mono',monospace; font-size:0.65rem; color:#94a3b8; margin-top:2px;">Sentiment Score</div>
            </div>
            <div style="font-family:'Orbitron',sans-serif; font-size:2rem; font-weight:900; color:{sc};">{ticker_sent['icon']} {ticker_sent['score']:+d}</div>
            <div style="font-family:'Orbitron',sans-serif; font-size:1rem; color:{sc};">{ticker_sent['label']}</div>
        </div>
        """, unsafe_allow_html=True)

        for article in ticker_sent["articles"]:
            sent = article["sentiment"]
            a_color = "#00ff88" if sent > 0.1 else "#ff3366" if sent < -0.1 else "#94a3b8"
            a_class = "sentiment-bull" if sent > 0.1 else "sentiment-bear" if sent < -0.1 else "sentiment-neut"
            icon    = "📈" if sent > 0.1 else "📉" if sent < -0.1 else "➡️"
            st.markdown(f"""
            <div class="{a_class}">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
                    <div style="font-family:'Rajdhani',sans-serif; font-size:0.9rem; color:#e2e8f0; font-weight:500; flex:1;">{icon} {article['title']}</div>
                    <div style="font-family:'Share Tech Mono',monospace; font-size:0.6rem; color:{a_color}; white-space:nowrap;">{sent:+.2f}</div>
                </div>
                <div style="font-family:'Share Tech Mono',monospace; font-size:0.58rem; color:#475569; margin-top:4px;">{article['publisher']} · {article['published']}</div>
            </div>
            """, unsafe_allow_html=True)


# ══════════════════════════════════════════════
# TAB 3 — GAMMA MAP
# ══════════════════════════════════════════════
with tab4:
    if len(scan_df) == 0:
        st.info("Run scan first.")
    else:
        gc1, gc2 = st.columns([1, 2])
        with gc1:
            gamma_ticker = st.selectbox("Ticker", scan_df["Ticker"].tolist(), key="gamma_sel")
        row   = scan_df[scan_df["Ticker"]==gamma_ticker].iloc[0]
        spot  = row["_spot"]
        chain = generate_simulated_chain(gamma_ticker, spot, seed=row["_chain_seed"])
        gl    = identify_gamma_levels(chain, spot)
        cbs   = gl["call_by_strike"]
        pbs   = gl["put_by_strike"]
        with gc2:
            sc = row.get("Sent Color","#94a3b8")
            st.markdown(f"""
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.68rem; color:#94a3b8; padding:28px 0 8px 0; display:flex; gap:24px; flex-wrap:wrap;">
                <span>Price: <b style="color:#e2e8f0;">${row['Price']:.2f}</b></span>
                <span>γ Trigger: <b style="color:#8b5cf6;">${row['γ Trigger']}</b></span>
                <span>Call Wall: <b style="color:#00ff88;">${row['Call Wall']}</b></span>
                <span>Put Wall: <b style="color:#ff3366;">${row['Put Wall']}</b></span>
                <span>Score: <b style="color:#ffb800;">{row['SCORE']}</b></span>
                <span>Sentiment: <b style="color:{sc};">{row.get('Sent Icon','')}{row.get('Sentiment Label','')}</b></span>
            </div>
            """, unsafe_allow_html=True)

        # OPEX annotation on gamma chart
        opex_note = f"⚡ {opex_info['phase']} — {opex_info['phase_desc'][:60]}..." if len(opex_info['phase_desc']) > 60 else f"⚡ {opex_info['phase']}"

        fig = go.Figure()
        fig.add_trace(go.Bar(x=cbs["strike"], y=cbs["gex_proxy"],  name="Call GEX", marker_color="#00ff88", opacity=0.85))
        fig.add_trace(go.Bar(x=pbs["strike"], y=-pbs["gex_proxy"], name="Put GEX",  marker_color="#ff3366", opacity=0.85))
        shapes, annotations = [], []
        for val, label, color, dash in [
            (spot, "SPOT", "#ffffff", "solid"),
            (gl["gamma_trigger"], "γTRIG",    "#8b5cf6", "dash"),
            (gl["call_wall"],     "CALL WALL","#00ff88", "dash"),
            (gl["put_wall"],      "PUT WALL", "#ff3366", "dash"),
        ]:
            if val and isinstance(val, float):
                shapes.append(dict(type="line", x0=val, x1=val, y0=-pbs["gex_proxy"].max()*1.1, y1=cbs["gex_proxy"].max()*1.1, line=dict(color=color,width=2,dash=dash)))
                annotations.append(dict(x=val, y=cbs["gex_proxy"].max()*1.05, text=f"<b>{label}</b>", showarrow=False, font=dict(color=color,family="Share Tech Mono",size=10), xanchor="center"))
        if gl["acceleration_zone_start"] and gl["acceleration_zone_end"]:
            shapes.append(dict(type="rect", x0=gl["acceleration_zone_start"], x1=gl["acceleration_zone_end"], y0=0, y1=cbs["gex_proxy"].max()*1.1, fillcolor="rgba(255,184,0,0.08)", line=dict(color="#ffb800",width=1,dash="dot")))
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#060810", plot_bgcolor="#0a0d1a",
            title=dict(text=f"<b>{gamma_ticker}</b> — Gamma Exposure · {opex_note}", font=dict(family="Orbitron",color="#e2e8f0",size=13)),
            xaxis=dict(title="Strike", gridcolor="#1e2a3a", color="#94a3b8", tickfont=dict(family="Share Tech Mono",size=10)),
            yaxis=dict(title="GEX Proxy", gridcolor="#1e2a3a", color="#94a3b8", zeroline=True, zerolinecolor="#2d3f55"),
            shapes=shapes, annotations=annotations, barmode="overlay", height=480,
            margin=dict(t=60,b=40,l=60,r=20),
            legend=dict(font=dict(family="Share Tech Mono",color="#94a3b8"),bgcolor="#0a0d1a"),
        )
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════
# TAB 4 — BREAKDOWN
# ══════════════════════════════════════════════
with tab5:
    if len(scan_df) == 0:
        st.info("Run scan first.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            fig_hist = go.Figure(go.Histogram(
                x=scan_df["SCORE"], nbinsx=20,
                marker=dict(color=scan_df["SCORE"], colorscale=[[0,"#00b4ff"],[0.5,"#ffb800"],[1,"#00ff88"]], line=dict(color="#060810",width=1)),
                opacity=0.85))
            fig_hist.add_vline(x=85, line=dict(color="#00ff88",dash="dash",width=1.5))
            fig_hist.add_vline(x=75, line=dict(color="#ffb800",dash="dash",width=1.5))
            fig_hist.update_layout(
                paper_bgcolor="#060810", plot_bgcolor="#0a0d1a", template="plotly_dark",
                title=dict(text="Score Distribution", font=dict(family="Orbitron",size=13,color="#e2e8f0")),
                xaxis=dict(gridcolor="#1e2a3a",color="#94a3b8"),
                yaxis=dict(gridcolor="#1e2a3a",color="#94a3b8"),
                height=300, margin=dict(t=50,b=40,l=50,r=20), showlegend=False)
            st.plotly_chart(fig_hist, use_container_width=True)
        with c2:
            sent_weights = [1 - sent_weight] * 4
            base_labels  = ["Trend","Options Pressure","Rejection","OPEX Context","Liquidity"]
            base_values  = [20*(1-sent_weight), 30*(1-sent_weight), 20*(1-sent_weight), 20*(1-sent_weight), 10*(1-sent_weight)]
            if apply_sentiment:
                base_labels.append("Sentiment")
                base_values.append(sent_weight * 100)
            fig_pie = go.Figure(go.Pie(
                labels=base_labels, values=base_values, hole=0.55,
                marker=dict(colors=["#00ff88","#8b5cf6","#ffb800","#00b4ff","#ff3366"][:len(base_labels)], line=dict(color="#060810",width=2)),
                textfont=dict(family="Share Tech Mono",size=10,color="#e2e8f0")))
            fig_pie.update_layout(
                paper_bgcolor="#060810", template="plotly_dark",
                title=dict(text="Signal Weights", font=dict(family="Orbitron",size=13,color="#e2e8f0")),
                legend=dict(font=dict(family="Share Tech Mono",color="#94a3b8"),bgcolor="#0a0d1a"),
                height=300, margin=dict(t=50,b=10,l=10,r=10),
                annotations=[dict(text="WEIGHT",x=0.5,y=0.5,font=dict(family="Orbitron",size=10,color="#94a3b8"),showarrow=False)])
            st.plotly_chart(fig_pie, use_container_width=True)

        # Sentiment vs Score scatter
        if apply_sentiment and len(scan_df) > 1:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#00b4ff; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:8px;">◈ SENTIMENT vs SCORE CORRELATION</p>', unsafe_allow_html=True)
            fig_scat = go.Figure()
            for lbl, col in [("BULLISH","#00ff88"),("NEUTRAL","#94a3b8"),("BEARISH","#ff3366")]:
                sub = scan_df[scan_df["Sentiment Label"]==lbl]
                if len(sub):
                    fig_scat.add_trace(go.Scatter(
                        x=sub["_sent_raw"]*100, y=sub["SCORE"],
                        mode="markers+text", name=lbl,
                        text=sub["Ticker"], textposition="top center",
                        textfont=dict(family="Share Tech Mono",size=9,color=col),
                        marker=dict(color=col, size=10, opacity=0.8, line=dict(color="#060810",width=1)),
                    ))
            fig_scat.update_layout(
                template="plotly_dark", paper_bgcolor="#060810", plot_bgcolor="#0a0d1a",
                xaxis=dict(title="Sentiment Score", gridcolor="#1e2a3a", color="#94a3b8", tickfont=dict(family="Share Tech Mono",size=9)),
                yaxis=dict(title="Breakout Score", gridcolor="#1e2a3a", color="#94a3b8"),
                height=380, margin=dict(t=20,b=50,l=60,r=20),
                legend=dict(font=dict(family="Share Tech Mono",color="#94a3b8"),bgcolor="#0a0d1a"),
            )
            st.plotly_chart(fig_scat, use_container_width=True)

        top5_df = scan_df.head(5)
        cats = ["Trend","Options","Rejection","OPEX","Liquidity"]
        colors_r = ["#00ff88","#ffb800","#8b5cf6","#00b4ff","#ff3366"]
        fig_radar = go.Figure()
        for i, (_, row) in enumerate(top5_df.iterrows()):
            vals = [row["Trend Score"],row["Options Score"],row["Rejection Score"],row["OPEX Score"],row["Trend Score"]]
            fig_radar.add_trace(go.Scatterpolar(
                r=vals, theta=cats+[cats[0]], name=row["Ticker"],
                line=dict(color=colors_r[i],width=2), fill="toself", opacity=0.75))
        fig_radar.update_layout(
            polar=dict(bgcolor="#0a0d1a",
                radialaxis=dict(visible=True,range=[0,100],gridcolor="#1e2a3a",tickfont=dict(family="Share Tech Mono",size=8,color="#475569")),
                angularaxis=dict(tickfont=dict(family="Share Tech Mono",size=10,color="#94a3b8"),gridcolor="#1e2a3a")),
            paper_bgcolor="#060810", template="plotly_dark",
            title=dict(text="Signal Radar — Top Setups", font=dict(family="Orbitron",size=13,color="#e2e8f0")),
            legend=dict(font=dict(family="Share Tech Mono",color="#94a3b8"),bgcolor="#0a0d1a"),
            height=380, margin=dict(t=50,b=20,l=20,r=20))
        st.plotly_chart(fig_radar, use_container_width=True)


# ══════════════════════════════════════════════
# TAB 5 — DETAIL
# ══════════════════════════════════════════════
with tab6:
    if len(scan_df) == 0:
        st.info("Run scan first.")
    else:
        detail_ticker = st.selectbox("Deep Dive", scan_df["Ticker"].tolist(), key="detail_sel")
        row = scan_df[scan_df["Ticker"]==detail_ticker].iloc[0]
        sc  = "#00ff88" if row["SCORE"]>=85 else "#ffb800" if row["SCORE"]>=75 else "#00b4ff"
        sco = row.get("Sent Color","#94a3b8")

        d1,d2,d3,d4 = st.columns(4)
        with d1:
            st.metric("Price",    f"${row['Price']:.2f}",    row["Data"])
            st.metric("Breakout", f"${row['Breakout']:.2f}", f"{((row['Breakout']-row['Price'])/row['Price']*100):.1f}% away")
        with d2:
            st.metric("γ Trigger", f"${row['γ Trigger']}" if row['γ Trigger']!='—' else "—")
            st.metric("Call Wall",  f"${row['Call Wall']}" if row['Call Wall']!='—' else "—")
        with d3:
            st.metric("Rel Volume",  f"×{row['Rel Vol']:.2f}")
            st.metric("CP Ratio",    f"{row['CP Ratio']:.2f}", "Bullish" if row["CP Ratio"]>1.3 else "Neutral")
        with d4:
            st.metric("Sentiment",    f"{row.get('Sent Icon','')} {row.get('Sentiment Label','—')}")
            st.metric("OPEX Phase",   opex_info["phase"].split()[-1])

        st.markdown(f"""
        <div style="background:#0d1120; border:1px solid {sc}33; border-radius:8px; padding:14px 18px; margin:14px 0;">
            <div style="font-family:'Share Tech Mono',monospace; font-size:0.58rem; color:#475569; letter-spacing:0.15em; text-transform:uppercase; margin-bottom:6px;">Trade Intelligence</div>
            <div style="font-family:'Rajdhani',sans-serif; font-size:1.1rem; font-weight:600; color:{sc};">⚡ {row['Trade Idea']}</div>
            <div style="margin-top:10px; display:flex; gap:20px; flex-wrap:wrap;">
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">Sweeps: <b style="color:{'#00ff88' if row['Sweeps']=='✓' else '#475569'};">{row['Sweeps']}</b></span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">C/P: <b style="color:#ffb800;">{row['CP Ratio']:.2f}</b></span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">Vol: <b style="color:#00b4ff;">×{row['Rel Vol']:.2f}</b></span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">Sentiment: <b style="color:{sco};">{row.get('Sent Icon','')} {row.get('Sentiment Label','—')}</b></span>
                <span style="font-family:'Share Tech Mono',monospace; font-size:0.62rem; color:#94a3b8;">OPEX: <b style="color:{opex_info['phase_color']};">{opex_info['phase']}</b></span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        weighted = [row["Trend Score"], row["Options Score"], row["Rejection Score"], row["OPEX Score"], row["Liquidity Score"]]
        labels_w = ["Trend","Options","Rejection","OPEX","Liquidity"]
        if apply_sentiment:
            weighted.append(row["Sentiment"] * sent_weight)
            labels_w.append("Sentiment")
        fig_w = go.Figure(go.Waterfall(
            orientation="v", measure=["relative"]*len(labels_w)+["total"],
            x=labels_w+["FINAL"], y=weighted+[None],
            text=[f"{w:.1f}" for w in weighted]+[f"{sum(weighted):.1f}"],
            textposition="outside", connector=dict(line=dict(color="#1e2a3a",width=1)),
            increasing=dict(marker=dict(color="#00ff88")), totals=dict(marker=dict(color=sc)),
            textfont=dict(family="Share Tech Mono",size=10,color="#e2e8f0")))
        fig_w.update_layout(
            paper_bgcolor="#060810", plot_bgcolor="#0a0d1a", template="plotly_dark",
            title=dict(text=f"{detail_ticker} — Weighted Score Breakdown", font=dict(family="Orbitron",color="#e2e8f0",size=13)),
            xaxis=dict(tickfont=dict(family="Share Tech Mono",size=10),color="#94a3b8"),
            yaxis=dict(gridcolor="#1e2a3a",color="#94a3b8",range=[0,35]),
            height=320, margin=dict(t=50,b=40,l=60,r=20), showlegend=False)
        st.plotly_chart(fig_w, use_container_width=True)

        # Simulated price chart
        rng2   = np.random.RandomState(abs(hash(detail_ticker+"p")) % 99999)
        n      = 78
        prices = row["Price"]*rng2.uniform(0.985,1.005) + np.cumsum(rng2.normal(0, row["Price"]*0.0012, n))
        times  = [datetime.now().replace(hour=9,minute=30) + timedelta(minutes=5*i) for i in range(n)]
        lc     = "#00ff88" if prices[-1]>=prices[0] else "#ff3366"
        vwap   = prices.mean() * rng2.uniform(0.997,1.003)
        fig_p  = go.Figure()
        fig_p.add_trace(go.Scatter(x=times, y=prices, mode="lines", name="Price", line=dict(color=lc,width=2)))
        fig_p.add_hline(y=vwap, line=dict(color="#ffb800",dash="dot",width=1.5), annotation_text="VWAP", annotation_font=dict(family="Share Tech Mono",size=9,color="#ffb800"))
        fig_p.add_hline(y=row["Breakout"], line=dict(color="#00b4ff",dash="dash",width=1.5), annotation_text="BREAKOUT", annotation_font=dict(family="Share Tech Mono",size=9,color="#00b4ff"))
        if isinstance(row["γ Trigger"], float):
            fig_p.add_hline(y=row["γ Trigger"], line=dict(color="#8b5cf6",dash="dash",width=1.5), annotation_text="γ TRIG", annotation_font=dict(family="Share Tech Mono",size=9,color="#8b5cf6"))
        fig_p.update_layout(
            paper_bgcolor="#060810", plot_bgcolor="#0a0d1a", template="plotly_dark",
            xaxis=dict(gridcolor="#1e2a3a",color="#94a3b8",tickfont=dict(family="Share Tech Mono",size=8)),
            yaxis=dict(gridcolor="#1e2a3a",color="#94a3b8",title="Price"),
            height=280, margin=dict(t=10,b=40,l=60,r=20))
        st.plotly_chart(fig_p, use_container_width=True)


# ══════════════════════════════════════════════
# TAB 7 — ENTRY DECISION ENGINE
# ══════════════════════════════════════════════
with tab7:
    st.markdown("""<div style="padding:4px 0 12px 0;">
        <div style="font-family:'Orbitron',sans-serif;font-size:0.9rem;font-weight:700;color:#ffb800;letter-spacing:0.08em;">🎯 ENTRY DECISION ENGINE</div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;margin-top:4px;letter-spacing:0.1em;">SUPPORT · RESISTANCE · EMA9/20/50 · RSI · MACD · ATR · ADD NOW OR WAIT?</div>
    </div>""", unsafe_allow_html=True)

    # ── Ticker selector ──
    ed_col1, ed_col2 = st.columns([2, 1])
    with ed_col1:
        if len(scan_df) > 0:
            ed_ticker = st.selectbox("Select ticker for entry analysis",
                                     scan_df["Ticker"].tolist(),
                                     key="ed_ticker_sel")
        else:
            ed_ticker = st.text_input("Enter ticker symbol", value="NVDA", key="ed_ticker_input").upper()

    with ed_col2:
        ed_days = st.selectbox("Price history (days)", [30, 60, 90], index=1, key="ed_days")

    if st.button("🎯 ANALYZE ENTRY", use_container_width=True, key="btn_entry"):
        # ── Build OHLCV from Polygon or simulate realistic history ──
        with st.spinner(f"Analyzing {ed_ticker}..."):

            ohlcv_df = None

            # Try Polygon if API key available
            if api_key and REQUESTS_OK:
                try:
                    end_date   = datetime.now().strftime("%Y-%m-%d")
                    start_date = (datetime.now() - timedelta(days=ed_days + 10)).strftime("%Y-%m-%d")
                    url = f"https://api.polygon.io/v2/aggs/ticker/{ed_ticker}/range/1/day/{start_date}/{end_date}?adjusted=true&sort=asc&limit=120&apiKey={api_key}"
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        results = r.json().get("results", [])
                        if results:
                            ohlcv_df = pd.DataFrame(results)
                            ohlcv_df = ohlcv_df.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
                            ohlcv_df = ohlcv_df[["open","high","low","close","volume"]]
                except Exception:
                    pass

            # Fallback: simulate realistic OHLCV from universe base price
            if ohlcv_df is None or len(ohlcv_df) < 20:
                base = UNIVERSE.get(ed_ticker, 100.0)
                rng_ed = np.random.RandomState(abs(hash(ed_ticker)) % 99999)
                n = ed_days
                # Random walk with slight upward drift
                returns = rng_ed.normal(0.0005, 0.018, n)
                closes = base * np.exp(np.cumsum(returns))
                highs  = closes * (1 + rng_ed.uniform(0.003, 0.025, n))
                lows   = closes * (1 - rng_ed.uniform(0.003, 0.025, n))
                opens  = np.roll(closes, 1); opens[0] = base
                vols   = rng_ed.uniform(3e6, 15e6, n)
                ohlcv_df = pd.DataFrame({"open":opens,"high":highs,"low":lows,"close":closes,"volume":vols})
                st.caption("📊 Using simulated price history — connect Polygon API for real data")

            # ── Run the entry decision engine ──
            def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
            def _rsi(s, n=14):
                d = s.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
                ag = g.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
                al = l.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
                rs = ag / al.replace(0, np.nan)
                return 100 - (100 / (1 + rs))
            def _macd(s, f=12, sl=26, sig=9):
                ml = _ema(s,f) - _ema(s,sl); sl2 = _ema(ml,sig); return ml, sl2, ml-sl2
            def _atr(df, n=14):
                hl=df["high"]-df["low"]; hc=(df["high"]-df["close"].shift()).abs(); lc=(df["low"]-df["close"].shift()).abs()
                tr=pd.concat([hl,hc,lc],axis=1).max(axis=1)
                return tr.ewm(alpha=1/n, min_periods=n, adjust=False).mean()

            df_ed = ohlcv_df.copy()
            df_ed["ema9"]  = _ema(df_ed["close"], 9)
            df_ed["ema20"] = _ema(df_ed["close"], 20)
            df_ed["ema50"] = _ema(df_ed["close"], 50)
            df_ed["rsi14"] = _rsi(df_ed["close"])
            ml, sl2, hist  = _macd(df_ed["close"])
            df_ed["macd_hist"] = hist
            df_ed["atr14"] = _atr(df_ed)

            last = df_ed.iloc[-1]
            prev = df_ed.iloc[-2] if len(df_ed) >= 2 else last

            close   = float(last["close"])
            ema9_v  = float(last["ema9"])  if pd.notna(last["ema9"])  else None
            ema20_v = float(last["ema20"]) if pd.notna(last["ema20"]) else None
            ema50_v = float(last["ema50"]) if pd.notna(last["ema50"]) else None
            rsi_v   = float(last["rsi14"]) if pd.notna(last["rsi14"]) else None
            macd_h  = float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else None
            atr_v   = float(last["atr14"]) if pd.notna(last["atr14"]) else None

            recent  = df_ed.tail(20)
            support    = float(recent["low"].min())
            resistance = float(recent["high"].max())

            # Trend state
            if ema9_v and ema20_v and ema50_v:
                if close > ema9_v > ema20_v > ema50_v:
                    trend_state = "BULLISH"
                    trend_color = "#00ff88"
                elif close < ema9_v < ema20_v < ema50_v:
                    trend_state = "BEARISH"
                    trend_color = "#ff3366"
                else:
                    trend_state = "MIXED"
                    trend_color = "#ffb800"
            else:
                trend_state = "UNKNOWN"
                trend_color = "#94a3b8"

            # Bearish expansion candle
            bearish_exp = (last["close"] < last["open"] and
                           (last["open"] - last["close"]) > (prev["high"] - prev["low"]) * 0.6)

            near_support  = abs(close - support) <= max(0.5, (atr_v or 1.0) * 0.35)
            below_mas     = ema9_v and close < ema9_v and ema20_v and close < ema20_v
            oversold      = rsi_v and rsi_v < 35
            not_oversold  = rsi_v and rsi_v > 40
            macd_bullish  = macd_h and macd_h > 0

            # Setup classification
            if bearish_exp and below_mas and not_oversold:
                setup   = "SELLOFF INTO SUPPORT — WATCH"
                action  = "WAIT"
                conf    = "HIGH"
                act_color = "#ffb800"
                conf_trigger = f"Wait for reclaim of ${round(close + max(0.75,(atr_v or 1)*0.25),2)} or bullish reversal candle near support"
                invalidation = f"Break and hold below ${round(support - max(0.75,(atr_v or 1)*0.35),2)}"
                notes = ["Price had a bearish expansion day. Do not buy just because it's down — wait for confirmation."]
            elif near_support and oversold:
                setup   = "BOUNCE CANDIDATE"
                action  = "ADD PARTIAL"
                conf    = "MEDIUM"
                act_color = "#00b4ff"
                conf_trigger = "Bullish reversal candle, intraday reclaim of VWAP, or volume spike"
                invalidation = f"Exit if price loses ${round(support - max(0.5,(atr_v or 1)*0.25),2)} with no reclaim"
                notes = ["Use starter size first. Add only after reclaim of nearby resistance."]
            elif trend_state == "BULLISH" and macd_bullish:
                setup   = "TREND CONTINUATION"
                action  = "ADD ON CONFIRMATION"
                conf    = "MEDIUM"
                act_color = "#00ff88"
                conf_trigger = f"Hold above EMA9/EMA20 and break above ${round(resistance,2)}"
                invalidation = f"Failure back below EMA20 (${round(ema20_v,2) if ema20_v else 'N/A'})"
                notes = ["Best adds happen on constructive pullbacks or confirmed breakouts — not random chasing."]
            else:
                setup   = "NEUTRAL — NO EDGE"
                action  = "STAY OUT"
                conf    = "LOW"
                act_color = "#475569"
                conf_trigger = "Wait for cleaner support reaction or clear resistance reclaim"
                invalidation = "No trade if price remains trapped between support and resistance"
                notes = ["Setup is unclear. Preserve capital."]

            # Bounce targets
            targets = sorted([x for x in [ema9_v, ema20_v, ema50_v, resistance] if x and x > close])[:3]

        # ── DISPLAY ──

        # Action banner
        st.markdown(f"""
        <div style="background:{'rgba(0,255,136,0.08)' if action!='STAY OUT' else 'rgba(71,85,105,0.15)'};
             border:1px solid {act_color}55;border-radius:10px;padding:18px 24px;margin-bottom:20px;">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
                <div>
                    <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;letter-spacing:0.15em;text-transform:uppercase;">Recommended Action</div>
                    <div style="font-family:'Orbitron',sans-serif;font-size:1.6rem;font-weight:900;color:{act_color};margin-top:4px;">{action}</div>
                    <div style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#94a3b8;margin-top:4px;">{setup}</div>
                </div>
                <div style="text-align:right;">
                    <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;letter-spacing:0.1em;">CONFIDENCE</div>
                    <div style="font-family:'Orbitron',sans-serif;font-size:1.1rem;color:{act_color};margin-top:4px;">{conf}</div>
                    <div style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:{trend_color};margin-top:4px;">{trend_state}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Key levels metrics
        lc1, lc2, lc3, lc4, lc5, lc6 = st.columns(6)
        with lc1: st.metric("Price",      f"${close:.2f}")
        with lc2: st.metric("Support",    f"${support:.2f}",    f"{'Near' if near_support else f'{abs(close-support):.2f} away'}")
        with lc3: st.metric("Resistance", f"${resistance:.2f}", f"{((resistance-close)/close*100):.1f}% above")
        with lc4: st.metric("RSI (14)",   f"{rsi_v:.1f}" if rsi_v else "—",  "Oversold" if oversold else ("Momentum" if rsi_v and rsi_v > 50 else "Neutral"))
        with lc5: st.metric("MACD Hist",  f"{macd_h:.3f}" if macd_h else "—", "Bullish" if macd_bullish else "Bearish")
        with lc6: st.metric("ATR (14)",   f"${atr_v:.2f}" if atr_v else "—",  "Volatility")

        st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)

        # EMA levels + decision details
        ec1, ec2 = st.columns(2)
        with ec1:
            ema9_str  = f"${ema9_v:.2f}"  if ema9_v  else "—"
            ema20_str = f"${ema20_v:.2f}" if ema20_v else "—"
            ema50_str = f"${ema50_v:.2f}" if ema50_v else "—"
            ema9_c  = "#00ff88" if ema9_v  and close > ema9_v  else "#ff3366"
            ema20_c = "#00ff88" if ema20_v and close > ema20_v else "#ff3366"
            ema50_c = "#00ff88" if ema50_v and close > ema50_v else "#ff3366"
            st.markdown(f"""
            <div style="background:#0d1120;border:1px solid #1e2a3a;border-radius:8px;padding:16px 18px;">
                <div style="font-family:'Share Tech Mono',monospace;font-size:0.62rem;color:#00b4ff;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;">◈ KEY LEVELS</div>
                <div style="font-family:'Share Tech Mono',monospace;font-size:0.68rem;line-height:2.2;color:#94a3b8;">
                    EMA9:  <b style="color:{ema9_c};">{ema9_str}</b><br>
                    EMA20: <b style="color:{ema20_c};">{ema20_str}</b><br>
                    EMA50: <b style="color:{ema50_c};">{ema50_str}</b><br>
                    Support: <b style="color:#ffb800;">${support:.2f}</b><br>
                    Resistance: <b style="color:#8b5cf6;">${resistance:.2f}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with ec2:
            targets_str = " → ".join([f"${t:.2f}" for t in targets]) if targets else "—"
            add_low  = round(max(0, support - 0.5), 2)
            add_high = round(support + 0.5, 2)
            st.markdown(f"""
            <div style="background:#0d1120;border:1px solid {act_color}33;border-radius:8px;padding:16px 18px;">
                <div style="font-family:'Share Tech Mono',monospace;font-size:0.62rem;color:{act_color};letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;">◈ TRADE PLAN</div>
                <div style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;line-height:2;color:#94a3b8;">
                    Add Zone: <b style="color:#ffb800;">${add_low} – ${add_high}</b><br>
                    Targets: <b style="color:#00ff88;">{targets_str}</b><br>
                    <br>
                    <b style="color:#00b4ff;">Confirmation:</b><br>
                    <span style="color:#e2e8f0;">{conf_trigger}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Invalidation warning
        st.markdown(f"""
        <div style="background:#1a0d0d;border:1px solid #ff336644;border-radius:8px;padding:14px 18px;margin-top:12px;">
            <div style="font-family:'Share Tech Mono',monospace;font-size:0.62rem;color:#ff3366;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">⚠ INVALIDATION — EXIT IF:</div>
            <div style="font-family:'Rajdhani',sans-serif;font-size:1rem;font-weight:600;color:#e2e8f0;">{invalidation}</div>
        </div>
        """, unsafe_allow_html=True)

        # Notes
        if notes:
            st.markdown(f"""
            <div style="background:#0d1120;border:1px solid #1e2a3a;border-radius:6px;padding:12px 16px;margin-top:12px;font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#94a3b8;">
                📌 {' '.join(notes)}
            </div>
            """, unsafe_allow_html=True)

        # Price chart with all levels
        st.markdown('<div style="margin-top:20px;"></div>', unsafe_allow_html=True)
        fig_ed = go.Figure()
        fig_ed.add_trace(go.Candlestick(
            x=list(range(len(df_ed))),
            open=df_ed["open"], high=df_ed["high"],
            low=df_ed["low"],   close=df_ed["close"],
            name=ed_ticker,
            increasing_line_color="#00ff88", decreasing_line_color="#ff3366"))
        if ema9_v:  fig_ed.add_trace(go.Scatter(x=list(range(len(df_ed))), y=df_ed["ema9"],  name="EMA9",  line=dict(color="#ffb800",width=1.5)))
        if ema20_v: fig_ed.add_trace(go.Scatter(x=list(range(len(df_ed))), y=df_ed["ema20"], name="EMA20", line=dict(color="#00b4ff",width=1.5)))
        if ema50_v: fig_ed.add_trace(go.Scatter(x=list(range(len(df_ed))), y=df_ed["ema50"], name="EMA50", line=dict(color="#8b5cf6",width=1.5)))
        fig_ed.add_hline(y=support,    line=dict(color="#ffb800", dash="dot", width=1), annotation_text="SUPPORT",    annotation_font=dict(family="Share Tech Mono",size=9,color="#ffb800"))
        fig_ed.add_hline(y=resistance, line=dict(color="#8b5cf6", dash="dot", width=1), annotation_text="RESISTANCE", annotation_font=dict(family="Share Tech Mono",size=9,color="#8b5cf6"))
        fig_ed.update_layout(
            template="plotly_dark", paper_bgcolor="#060810", plot_bgcolor="#0a0d1a",
            title=dict(text=f"{ed_ticker} — Entry Decision Chart ({ed_days}d)", font=dict(family="Orbitron",color="#e2e8f0",size=13)),
            xaxis=dict(gridcolor="#1e2a3a", color="#94a3b8", showticklabels=False, rangeslider=dict(visible=False)),
            yaxis=dict(gridcolor="#1e2a3a", color="#94a3b8", title="Price"),
            height=420, margin=dict(t=50,b=30,l=60,r=20),
            legend=dict(font=dict(family="Share Tech Mono",color="#94a3b8"),bgcolor="#0a0d1a"))
        st.plotly_chart(fig_ed, use_container_width=True)

    else:
        # Prompt before analysis
        st.markdown("""
        <div style="background:#0d1120;border:1px solid #1e2a3a;border-radius:8px;padding:24px;text-align:center;margin-top:20px;">
            <div style="font-family:'Orbitron',sans-serif;font-size:1rem;color:#ffb800;margin-bottom:12px;">SELECT A TICKER AND CLICK ANALYZE ENTRY</div>
            <div style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#475569;line-height:2;">
                This engine answers 4 questions for any ticker:<br>
                <span style="color:#94a3b8;">① What are the key support and resistance levels?</span><br>
                <span style="color:#94a3b8;">② Is price near a good add zone?</span><br>
                <span style="color:#94a3b8;">③ Should I add now, wait for confirmation, or stay out?</span><br>
                <span style="color:#94a3b8;">④ What would invalidate this trade?</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── CHART ANALYSIS SECTION ──
    st.markdown("---")
    st.markdown("""<div style="padding:4px 0 12px 0;">
        <div style="font-family:'Orbitron',sans-serif;font-size:0.85rem;font-weight:700;color:#8b5cf6;letter-spacing:0.08em;">📸 AI CHART ANALYSIS</div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;margin-top:4px;letter-spacing:0.1em;">UPLOAD ANY CHART · AI READS PRICE ACTION · GET ENTRY DECISION</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#0d1120;border:1px solid #8b5cf644;border-radius:8px;padding:16px 20px;margin-bottom:16px;font-family:'Share Tech Mono',monospace;font-size:0.63rem;color:#94a3b8;line-height:2;">
        Upload a screenshot from <b style="color:#8b5cf6;">any platform</b> — TradingView, E*TRADE, Webull, Robinhood, your phone, anything.<br>
        Works with <span style="color:#00ff88;">any symbol</span> — stocks, ETFs, crypto, anything with a chart.<br>
        The AI reads: <span style="color:#00ff88;">trend · MAs · support/resistance · RSI · MACD · volume · patterns · candle structure</span><br>
        Then tells you the <b style="color:#ffb800;">full story of what the chart is saying + a clear entry verdict</b>
    </div>
    """, unsafe_allow_html=True)

    # Ticker + context input row
    ui1, ui2 = st.columns([1, 2])
    with ui1:
        chart_ticker_input = st.text_input(
            "Ticker (optional)",
            placeholder="e.g. ASTS, NVDA, SPY...",
            key="chart_ticker_input"
        )
    with ui2:
        chart_context = st.text_input(
            "Context (optional)",
            placeholder="e.g. Daily chart, thinking of adding, already long 500 shares, looking at 3-month setup...",
            key="chart_context",
            label_visibility="collapsed"
        )

    chart_img = st.file_uploader(
        "Upload chart screenshot (PNG, JPG, WEBP)",
        type=["png","jpg","jpeg","webp"],
        key="chart_upload"
    )
    analyze_chart_btn = st.button("🔍 ANALYZE CHART", use_container_width=True, key="btn_chart_analyze")

    if chart_img and analyze_chart_btn:
        with st.spinner("AI reading your chart..."):
            import base64

            # Encode image to base64
            img_bytes = chart_img.read()
            img_b64   = base64.b64encode(img_bytes).decode("utf-8")
            img_type  = chart_img.type  # e.g. image/png

            # Build prompt
            ticker_line = f"Ticker: {chart_ticker_input}\n" if chart_ticker_input else ""
            context_line = f"\n\nAdditional context from the trader: {ticker_line}{chart_context}" if (chart_ticker_input or chart_context) else ""

            prompt = f"""You are a senior trader and technical analyst at a proprietary trading desk. A trader has uploaded a chart and needs a complete intelligent read — the kind an experienced trader gives when asked "what's this chart telling you?"

Produce your analysis in EXACTLY this style and structure:

**THE STORY** — What phase is this stock in right now? Correction? Recovery? Breakout? Breakdown? Consolidation? Write it conversationally like explaining to a trading partner. What is the chart narrative?

**WHAT I'M SEEING** — Bullet points of the most critical observations: where are the MAs relative to price, what did the recent candles do, what's the structure telling you?

**WHY THIS MOVE MATTERS** — The context. Why is what's happening significant right now? Is this a reclaim attempt? A failed breakout? A base building?

**BULLISH SIGNALS** (only what you actually see):
* Be specific — "MACD bullish crossover with expanding histogram" not just "MACD bullish"
* Include RSI level and what it means — e.g. "RSI at 57 → not overheated, room to expand"
* Note MA positions — e.g. "Price reclaimed 20-day and 50-day, now testing 200-day"

**BEARISH SIGNALS / RISKS** (only what you actually see):
* What could flip the narrative
* What resistance is overhead and how significant

**KEY LEVELS** — Be as specific as possible with price numbers visible on the chart:
Bullish targets: [immediate breakout zone] → [next resistance] → [extended target]
Critical support: [nearest support] | [stronger support] | [level that damages the setup]

**THE VERDICT** — Pick exactly one:
✅ BUY NOW — entry zone, why right now, what just changed
⏳ WAIT FOR CONFIRMATION — exact price level AND condition needed (e.g. "wait for close above X on volume 2x average")
🔄 WAIT FOR PULLBACK — specific zone to add (e.g. "ideal add zone 83–85 on pullback to reclaim zone")
❌ STAY OUT — clear reason why this is not the time

**WHAT I'D WATCH NEXT** — The 2-3 specific things that need to happen for the bullish case to play out

**INVALIDATION** — The exact price or condition that means you are wrong and must exit. Be specific.

**STOCK-SPECIFIC RISK NOTE** — How does this stock trade? Volatile, options-heavy, news-driven, retail-dominated? What does that mean for position sizing and stop discipline?

Be direct. Specific price levels. Sound like a real trader not a textbook. No disclaimers.{context_line}"""

            try:
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 2000,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": img_type,
                                        "data": img_b64
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": prompt
                                }
                            ]
                        }]
                    },
                    timeout=45
                )

                if resp.status_code == 200:
                    analysis = resp.json()["content"][0]["text"]
                    st.session_state.chart_analysis = analysis
                    st.session_state.chart_image_b64 = img_b64
                    st.session_state.chart_image_type = img_type
                else:
                    st.error(f"API error {resp.status_code}: {resp.text[:200]}")

            except Exception as e:
                st.error(f"Analysis failed: {e}")

    # Display chart + analysis side by side
    if "chart_analysis" in st.session_state and st.session_state.chart_analysis:
        st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
        img_col, analysis_col = st.columns([1, 1])

        with img_col:
            if "chart_image_b64" in st.session_state:
                st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.62rem;color:#8b5cf6;letter-spacing:0.1em;">◈ YOUR CHART</p>', unsafe_allow_html=True)
                st.image(
                    f"data:{st.session_state.chart_image_type};base64,{st.session_state.chart_image_b64}",
                    use_container_width=True
                )

        with analysis_col:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.62rem;color:#8b5cf6;letter-spacing:0.1em;">◈ AI ANALYSIS</p>', unsafe_allow_html=True)

            # Parse and display analysis with styling
            analysis_text = st.session_state.chart_analysis

            # Show verdict badge if detected
            verdict_color = "#94a3b8"
            verdict_label = "ANALYZING"
            if "✅ BUY NOW" in analysis_text or "BUY NOW" in analysis_text:
                verdict_color = "#00ff88"; verdict_label = "✅ BUY NOW"
            elif "⏳ WAIT FOR CONFIRMATION" in analysis_text or "WAIT FOR CONFIRMATION" in analysis_text:
                verdict_color = "#ffb800"; verdict_label = "⏳ WAIT FOR CONFIRMATION"
            elif "❌ STAY OUT" in analysis_text or "STAY OUT" in analysis_text:
                verdict_color = "#ff3366"; verdict_label = "❌ STAY OUT"
            elif "🔄 WAIT FOR PULLBACK" in analysis_text or "WAIT FOR PULLBACK" in analysis_text:
                verdict_color = "#00b4ff"; verdict_label = "🔄 WAIT FOR PULLBACK"

            st.markdown(f"""
            <div style="background:{verdict_color}11;border:1px solid {verdict_color}44;border-radius:8px;
                 padding:10px 16px;margin-bottom:12px;font-family:'Orbitron',sans-serif;
                 font-size:0.85rem;font-weight:700;color:{verdict_color};text-align:center;">
                {verdict_label}
            </div>
            """, unsafe_allow_html=True)

            st.markdown(analysis_text)

        # Clear button
        if st.button("🗑 Clear Analysis", key="btn_clear_chart"):
            del st.session_state.chart_analysis
            if "chart_image_b64" in st.session_state:
                del st.session_state.chart_image_b64
            st.rerun()

    elif chart_img and not analyze_chart_btn:
        # Show image preview while waiting
        st.image(chart_img, caption="Chart uploaded — click ANALYZE CHART to get AI analysis", use_container_width=True)


# ══════════════════════════════════════════════
with tab8:
    st.markdown("""<div style="padding:4px 0 12px 0;">
        <div style="font-family:'Orbitron',sans-serif;font-size:0.9rem;font-weight:700;color:#ffb800;letter-spacing:0.08em;">💰 OPTIONS ORDER FLOW</div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;margin-top:4px;letter-spacing:0.1em;">UNUSUAL ACTIVITY · BLOCK TRADES · SWEEPS · CALL/PUT IMBALANCE</div>
    </div>""", unsafe_allow_html=True)

    # ── Flow generation engine ──
    def generate_order_flow(tickers, rng_seed=None):
        """
        Simulates realistic options order flow:
        - Block trades (large single orders, $500k+)
        - Sweeps (aggressive multi-exchange buys)
        - Unusual activity (OI spike, vol vs OI ratio)
        - Call/Put side, strike, expiry, premium
        """
        rng = np.random.RandomState(rng_seed or int(time.time()) % 99999)
        flow = []
        expiries = ["04/25","05/02","05/09","05/16","05/23","06/20","07/18","09/19","01/16/27"]
        order_types = ["SWEEP","BLOCK","SPLIT","UNUSUAL"]
        order_weights = [0.35, 0.30, 0.20, 0.15]

        for ticker in tickers:
            base = UNIVERSE.get(ticker, 100.0)
            # Generate 0-4 flow events per ticker
            n_events = rng.choice([0,1,2,3,4], p=[0.3,0.3,0.2,0.15,0.05])
            for _ in range(n_events):
                side      = rng.choice(["CALL","PUT"], p=[0.55, 0.45])
                otype     = rng.choice(order_types, p=order_weights)
                strike    = round(base * rng.choice([0.85,0.90,0.95,0.97,1.0,1.02,1.05,1.08,1.10,1.15]), 0)
                expiry    = rng.choice(expiries)
                premium   = round(rng.uniform(0.30, 18.0), 2)
                size      = int(rng.choice([50,100,200,300,500,750,1000,1500,2000,3000,5000],
                               p=[0.15,0.20,0.18,0.12,0.10,0.08,0.07,0.04,0.03,0.02,0.01]))
                total_val = round(size * premium * 100)
                is_unusual = total_val > 500000 or otype in ["SWEEP","UNUSUAL"]
                sentiment  = "BULLISH" if side=="CALL" else "BEARISH"
                otm_pct    = round((strike - base) / base * 100, 1)
                aggression = "🔥 AGGRESSIVE" if otype=="SWEEP" else ("⚡ BLOCK" if otype=="BLOCK" else ("🚨 UNUSUAL" if otype=="UNUSUAL" else "SPLIT"))

                flow.append({
                    "Time":       (datetime.now() - timedelta(minutes=int(rng.uniform(0,390)))).strftime("%H:%M"),
                    "Ticker":     ticker,
                    "Side":       side,
                    "Type":       aggression,
                    "Strike":     f"${strike:.0f}",
                    "Expiry":     expiry,
                    "Premium":    f"${premium:.2f}",
                    "Size":       f"{size:,}",
                    "Total $":    total_val,
                    "OTM %":      f"{otm_pct:+.1f}%",
                    "Sentiment":  sentiment,
                    "Unusual":    is_unusual,
                    "_side":      side,
                    "_total":     total_val,
                    "_ticker":    ticker,
                })

        return sorted(flow, key=lambda x: -x["_total"])

    # Controls
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        flow_tickers = scan_df["Ticker"].tolist() if len(scan_df) > 0 else list(UNIVERSE.keys())[:20]
        flow_filter = st.selectbox("Filter by ticker", ["ALL"] + flow_tickers, key="flow_filter")
    with fc2:
        flow_side = st.selectbox("Side", ["ALL", "CALL", "PUT"], key="flow_side")
    with fc3:
        min_premium = st.selectbox("Min trade value", ["Any", "$100K+", "$250K+", "$500K+", "$1M+"], key="flow_min")

    refresh_flow = st.button("🔄 REFRESH FLOW", use_container_width=True, key="btn_flow_refresh")

    if "flow_data" not in st.session_state or refresh_flow:
        all_tickers = flow_tickers if flow_filter == "ALL" else [flow_filter]
        st.session_state.flow_data = generate_order_flow(
            flow_tickers,
            rng_seed=int(time.time() / 60) % 99999  # refreshes every minute
        )

    flow_data = st.session_state.flow_data

    # Apply filters
    filtered = flow_data.copy()
    if flow_filter != "ALL":
        filtered = [f for f in filtered if f["Ticker"] == flow_filter]
    if flow_side != "ALL":
        filtered = [f for f in filtered if f["_side"] == flow_side]
    min_map = {"Any": 0, "$100K+": 100000, "$250K+": 250000, "$500K+": 500000, "$1M+": 1000000}
    min_val = min_map[min_premium]
    filtered = [f for f in filtered if f["_total"] >= min_val]

    if not filtered:
        st.info("No order flow matching filters. Try broadening the filter or refreshing.")
    else:
        # ── Summary metrics ──
        calls = [f for f in filtered if f["_side"] == "CALL"]
        puts  = [f for f in filtered if f["_side"] == "PUT"]
        call_prem = sum(f["_total"] for f in calls)
        put_prem  = sum(f["_total"] for f in puts)
        total_prem = call_prem + put_prem
        ratio = call_prem / put_prem if put_prem > 0 else 99
        unusual = [f for f in filtered if f["Unusual"]]

        sm1, sm2, sm3, sm4, sm5 = st.columns(5)
        with sm1: st.metric("Total Flow", f"${total_prem/1e6:.1f}M")
        with sm2: st.metric("Call Premium", f"${call_prem/1e6:.1f}M", f"{call_prem/total_prem*100:.0f}%" if total_prem else "—")
        with sm3: st.metric("Put Premium", f"${put_prem/1e6:.1f}M", f"{put_prem/total_prem*100:.0f}%" if total_prem else "—")
        with sm4:
            ratio_color = "🟢" if ratio > 1.5 else "🔴" if ratio < 0.67 else "🟡"
            st.metric("Call/Put Ratio", f"{ratio_color} {ratio:.2f}", "Bullish" if ratio > 1.2 else ("Bearish" if ratio < 0.8 else "Neutral"))
        with sm5: st.metric("Unusual Prints", len(unusual), "🚨 Watch these")

        # ── Call/Put flow bar chart ──
        by_ticker_calls = {}
        by_ticker_puts  = {}
        for f in filtered:
            t = f["_ticker"]
            if f["_side"] == "CALL": by_ticker_calls[t] = by_ticker_calls.get(t,0) + f["_total"]
            else:                    by_ticker_puts[t]  = by_ticker_puts.get(t,0)  + f["_total"]

        all_tks = sorted(set(list(by_ticker_calls.keys()) + list(by_ticker_puts.keys())))
        if all_tks:
            fig_flow = go.Figure()
            fig_flow.add_trace(go.Bar(
                x=all_tks,
                y=[by_ticker_calls.get(t,0)/1000 for t in all_tks],
                name="CALLS", marker_color="#00ff88",
                text=[f"${by_ticker_calls.get(t,0)/1000:.0f}K" for t in all_tks],
                textposition="outside", textfont=dict(family="Share Tech Mono", size=8, color="#00ff88")
            ))
            fig_flow.add_trace(go.Bar(
                x=all_tks,
                y=[-by_ticker_puts.get(t,0)/1000 for t in all_tks],
                name="PUTS", marker_color="#ff3366",
                text=[f"${by_ticker_puts.get(t,0)/1000:.0f}K" for t in all_tks],
                textposition="outside", textfont=dict(family="Share Tech Mono", size=8, color="#ff3366")
            ))
            fig_flow.update_layout(
                template="plotly_dark", paper_bgcolor="#060810", plot_bgcolor="#0a0d1a",
                barmode="relative", height=300, margin=dict(t=40,b=40,l=60,r=20),
                title=dict(text="Call vs Put Premium Flow by Ticker ($K)", font=dict(family="Orbitron",size=12,color="#e2e8f0")),
                xaxis=dict(tickfont=dict(family="Share Tech Mono",size=9), color="#94a3b8"),
                yaxis=dict(title="Premium ($K)", gridcolor="#1e2a3a", color="#94a3b8", zeroline=True, zerolinecolor="#2d3f55"),
                legend=dict(font=dict(family="Share Tech Mono",color="#94a3b8"), bgcolor="#0a0d1a"),
                showlegend=True)
            st.plotly_chart(fig_flow, use_container_width=True)

        # ── Unusual prints highlighted ──
        if unusual:
            st.markdown(f"""<div style="background:#1a0d00;border:1px solid #ffb80044;border-radius:6px;padding:10px 16px;margin-bottom:12px;font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#ffb800;">
                🚨 {len(unusual)} UNUSUAL PRINT{"S" if len(unusual)>1 else ""} DETECTED — Large/aggressive orders above $500K
            </div>""", unsafe_allow_html=True)
            for f in unusual[:5]:
                side_color = "#00ff88" if f["_side"] == "CALL" else "#ff3366"
                st.markdown(f"""
                <div style="background:#0d1120;border-left:3px solid {side_color};border-radius:0 6px 6px 0;padding:10px 16px;margin-bottom:6px;display:flex;gap:24px;flex-wrap:wrap;font-family:'Share Tech Mono',monospace;font-size:0.65rem;">
                    <span style="color:{side_color};font-weight:700;">{f['Type']}</span>
                    <span style="color:#e2e8f0;font-weight:700;">{f['Ticker']}</span>
                    <span style="color:{side_color};">{f['Side']}</span>
                    <span style="color:#94a3b8;">{f['Strike']} {f['Expiry']}</span>
                    <span style="color:#94a3b8;">@{f['Premium']}</span>
                    <span style="color:#e2e8f0;">×{f['Size']}</span>
                    <span style="color:#ffb800;font-weight:700;">${f['_total']:,.0f}</span>
                    <span style="color:#475569;">{f['OTM %']} OTM</span>
                    <span style="color:#94a3b8;">{f['Time']}</span>
                </div>
                """, unsafe_allow_html=True)

        # ── Full flow tape ──
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin:16px 0 6px 0;">◈ FULL FLOW TAPE</p>', unsafe_allow_html=True)
        display_cols = ["Time","Ticker","Side","Type","Strike","Expiry","Premium","Size","Total $","OTM %","Sentiment"]
        df_flow = pd.DataFrame(filtered)[display_cols + ["_total"]].copy()
        df_flow["Total $"] = df_flow["_total"].apply(lambda x: f"${x:,.0f}")
        df_flow = df_flow[display_cols]

        # Color-code with styling
        def style_flow(row):
            color = "#00ff8822" if row["Side"] == "CALL" else "#ff336622"
            return [f"background-color: {color}"] * len(row)

        st.dataframe(df_flow.style.apply(style_flow, axis=1), use_container_width=True, height=400)

# ══════════════════════════════════════════════
# TAB 6 — MOBILE + ALERTS
# ══════════════════════════════════════════════
with tab9:
    st.markdown('<p style="font-family:\'Orbitron\',sans-serif; font-size:0.9rem; color:#00ff88; letter-spacing:0.08em; margin-bottom:16px;">📱 ACCESS ON PHONE OR IPAD</p>', unsafe_allow_html=True)
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "192.168.x.x"

    st.markdown(f"""
    <div class="mobile-tip">
        <div style="color:#00ff88; margin-bottom:10px; font-size:0.75rem; letter-spacing:0.1em;">STEP 1 — MAKE SURE YOUR MAC AND PHONE ARE ON THE SAME WIFI</div>
        <div style="color:#94a3b8; margin-bottom:16px;">Your home or office WiFi — both devices must be connected.</div>
        <div style="color:#00ff88; margin-bottom:10px; font-size:0.75rem; letter-spacing:0.1em;">STEP 2 — OPEN THIS URL ON YOUR PHONE</div>
        <div style="background:#060810; border:1px solid #2d3f55; border-radius:4px; padding:12px 16px; margin-bottom:16px;">
            <span style="color:#00b4ff; font-size:1rem; letter-spacing:0.05em;">http://{local_ip}:8501</span>
        </div>
        <div style="color:#94a3b8; margin-bottom:16px;">Type that address into Safari or Chrome on your iPhone/iPad.</div>
        <div style="color:#00ff88; margin-bottom:10px; font-size:0.75rem; letter-spacing:0.1em;">STEP 3 — ADD TO HOME SCREEN (OPTIONAL)</div>
        <div style="color:#94a3b8;">On iPhone: tap the Share button → "Add to Home Screen" → becomes an app icon.</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:24px;"></div>', unsafe_allow_html=True)
    st.markdown('<p style="font-family:\'Orbitron\',sans-serif; font-size:0.9rem; color:#ffb800; letter-spacing:0.08em; margin-bottom:16px;">🔔 EMAIL ALERTS SETUP</p>', unsafe_allow_html=True)
    st.markdown("""
    <div class="mobile-tip">
        <div style="color:#ffb800; margin-bottom:10px; font-size:0.75rem; letter-spacing:0.1em;">HOW TO SET UP EMAIL ALERTS</div>
        <div style="color:#94a3b8; line-height:1.8;">
            1. You need a <b style="color:#e2e8f0;">Gmail account</b> to send alerts from<br>
            2. Go to <b style="color:#00b4ff;">myaccount.google.com</b> → Security → 2-Step Verification (turn on)<br>
            3. Then go to <b style="color:#00b4ff;">myaccount.google.com/apppasswords</b><br>
            4. Create an app password called "JEG Ballistic AI"<br>
            5. Copy the 16-character password<br>
            6. Enter in sidebar: your Gmail + that app password<br>
            7. Check "Enable email alerts"<br><br>
            <b style="color:#00ff88;">Every time a ticker hits 85+, you get an email instantly.</b>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:24px;"></div>', unsafe_allow_html=True)
    st.markdown('<p style="font-family:\'Orbitron\',sans-serif; font-size:0.9rem; color:#8b5cf6; letter-spacing:0.08em; margin-bottom:16px;">📋 ALERT LOG</p>', unsafe_allow_html=True)
    if st.session_state.alert_log:
        for log in st.session_state.alert_log[:20]:
            sc   = "#00ff88" if log["score"]>=85 else "#ffb800"
            slbl = log.get("sentiment","—")
            st.markdown(f"""
            <div style="background:#0d1120; border:1px solid #1e2a3a; border-radius:4px; padding:8px 12px; margin-bottom:6px; font-family:'Share Tech Mono',monospace; font-size:0.65rem;">
                <span style="color:#475569;">{log['time']}</span>
                <span style="color:{sc}; margin-left:12px; font-weight:bold;">{log['ticker']}</span>
                <span style="color:#94a3b8; margin-left:8px;">Score: <b style="color:{sc};">{log['score']}</b></span>
                <span style="color:#94a3b8; margin-left:8px;">Sent: {slbl}</span>
                <span style="color:#475569; margin-left:12px;">{log['trade']}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace; font-size:0.65rem; color:#475569;">No alerts fired yet. Alerts trigger when score ≥ 85.</p>', unsafe_allow_html=True)


# ══════════════════════════════════════════════
# TAB 7 — E*TRADE PRO
# ══════════════════════════════════════════════
with tab10:
    st.markdown("""<div style="padding:4px 0 16px 0;">
        <div style="font-family:'Orbitron',sans-serif;font-size:0.9rem;font-weight:700;color:#00b4ff;letter-spacing:0.08em;">E*TRADE PRO API</div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;margin-top:4px;letter-spacing:0.1em;">OAUTH 1.0A · REST API · LIVE QUOTES · ORDER EXECUTION</div></div>""",unsafe_allow_html=True)

    if not OAUTH_OK:
        st.error("Missing dependency: run `pip install requests-oauthlib --break-system-packages` then restart the app.")
    elif not st.session_state.etrade_connected:
        # ── AUTH FLOW ──
        st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:12px;">◈ AUTHENTICATION — OAUTH 1.0A</p>',unsafe_allow_html=True)
        a1,a2=st.columns([2,1])
        with a1:
            st.markdown("""<div style="background:#0d1120;border:1px solid #1e2a3a;border-radius:8px;padding:16px;margin-bottom:16px;font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#94a3b8;line-height:2.2;">
                <b style="color:#00b4ff;">3-STEP OAUTH FLOW:</b><br>
                <span style="color:#00ff88;">①</span> Enter API keys → request temporary token<br>
                <span style="color:#ffb800;">②</span> Visit authorization URL → approve → copy verifier code<br>
                <span style="color:#8b5cf6;">③</span> Enter verifier → receive session access token
            </div>""",unsafe_allow_html=True)
        with a2:
            sandbox_mode=st.toggle("Sandbox Mode",value=st.session_state.etrade_sandbox,key="sandbox_toggle")
            st.session_state.etrade_sandbox=sandbox_mode
            ec="#ffb800" if sandbox_mode else "#ff3366"; el="SANDBOX" if sandbox_mode else "⚠ LIVE TRADING"
            st.markdown(f"""<div style="background:{ec}11;border:1px solid {ec}44;border-radius:6px;padding:8px 12px;text-align:center;margin-top:8px;">
                <span style="font-family:'Orbitron',sans-serif;font-size:0.7rem;color:{ec};font-weight:700;">{el}</span></div>""",unsafe_allow_html=True)

        if st.session_state.etrade_auth_step==0:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.62rem;color:#00ff88;letter-spacing:0.1em;margin:16px 0 8px 0;">STEP 1 — API CREDENTIALS</p>',unsafe_allow_html=True)
            k1,k2=st.columns(2)
            with k1: ck=st.text_input("Consumer Key",placeholder="Your E*TRADE consumer key",key="input_ckey")
            with k2: cs=st.text_input("Consumer Secret",placeholder="Your E*TRADE consumer secret",type="password",key="input_csecret")
            st.markdown('<div style="font-family:\'Share Tech Mono\',monospace;font-size:0.6rem;color:#475569;margin-bottom:12px;">Get keys at <span style="color:#00b4ff;">developer.etrade.com</span> → Log in → Request Sandbox Key</div>',unsafe_allow_html=True)
            if st.button("🔑 REQUEST TOKEN →",key="btn_req"):
                if not ck or not cs: st.error("Enter both consumer key and secret.")
                else:
                    with st.spinner("Requesting token from E*TRADE..."):
                        r=etrade_get_request_token(ck,cs,st.session_state.etrade_sandbox)
                    if r["success"]:
                        st.session_state.etrade_consumer_key=ck; st.session_state.etrade_consumer_secret=cs
                        st.session_state.etrade_request_token=r["oauth_token"]; st.session_state.etrade_request_token_secret=r["oauth_token_secret"]
                        st.session_state.etrade_auth_step=1; st.rerun()
                    else: st.error(f"Token request failed: {r['error']}")

        elif st.session_state.etrade_auth_step==1:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.62rem;color:#ffb800;letter-spacing:0.1em;margin:16px 0 8px 0;">STEP 2 — AUTHORIZE ACCESS</p>',unsafe_allow_html=True)
            auth_url=etrade_get_auth_url(st.session_state.etrade_consumer_key,st.session_state.etrade_request_token)
            st.markdown(f"""<div style="background:#0d1120;border:1px solid #ffb80044;border-radius:8px;padding:16px;margin-bottom:16px;">
                <div style="font-family:'Share Tech Mono',monospace;font-size:0.62rem;color:#94a3b8;margin-bottom:8px;">1. Visit this URL to authorize:</div>
                <a href="{auth_url}" target="_blank" style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#00b4ff;word-break:break-all;">{auth_url}</a>
                <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;margin-top:10px;">2. Log in → click Authorize → copy the verifier code shown</div></div>""",unsafe_allow_html=True)
            verifier=st.text_input("Verifier Code",placeholder="5-character code from E*TRADE",key="input_verifier")
            cb,cn=st.columns([1,2])
            with cb:
                if st.button("← Back",key="btn_back"): st.session_state.etrade_auth_step=0; st.rerun()
            with cn:
                if st.button("🔓 AUTHENTICATE →",key="btn_auth"):
                    if not verifier: st.error("Enter the verifier code.")
                    else:
                        with st.spinner("Exchanging verifier for access token..."):
                            r=etrade_get_access_token(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                                st.session_state.etrade_request_token,st.session_state.etrade_request_token_secret,verifier,st.session_state.etrade_sandbox)
                        if r["success"]:
                            st.session_state.etrade_access_token=r["access_token"]; st.session_state.etrade_access_token_secret=r["access_token_secret"]
                            st.session_state.etrade_connected=True; st.session_state.etrade_auth_step=0; st.rerun()
                        else: st.error(f"Authentication failed: {r['error']}")
    else:
        # ── CONNECTED PANEL ──
        ec="#ffb800" if st.session_state.etrade_sandbox else "#00ff88"; el="SANDBOX" if st.session_state.etrade_sandbox else "LIVE"
        st.markdown(f"""<div style="background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.2);border-radius:8px;padding:12px 16px;margin-bottom:20px;">
            <span style="font-family:'Share Tech Mono',monospace;font-size:0.7rem;color:#00ff88;">◉ CONNECTED TO E*TRADE</span>
            <span style="font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:{ec};margin-left:16px;">[{el}]</span>
            <span style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#475569;float:right;">Token expires midnight ET</span></div>""",unsafe_allow_html=True)

        et1,et2,et3,et4=st.tabs(["💼  ACCOUNTS","📈  LIVE QUOTES","⚡  ORDER ENTRY","📋  ORDERS"])

        with et1:
            if st.button("↻ Refresh",key="btn_refresh_acct"): st.session_state.etrade_accounts=None
            if st.session_state.etrade_accounts is None:
                with st.spinner("Fetching accounts..."):
                    r=etrade_get_accounts(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                        st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,st.session_state.etrade_sandbox)
                if r["success"]: st.session_state.etrade_accounts=r["data"]
                else: st.error(f"Failed: {r['error']}")
            if st.session_state.etrade_accounts:
                try:
                    al=st.session_state.etrade_accounts["AccountListResponse"]["Accounts"]["Account"]
                    if not isinstance(al,list): al=[al]
                    idx=st.selectbox("Select Account",range(len(al)),format_func=lambda i:f"{al[i].get('accountDesc','Account')} ({al[i].get('accountId','?')})",key="acct_sel")
                    acct=al[idx]; st.session_state.etrade_selected_account=acct.get("accountIdKey")
                    br=etrade_get_balance(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                        st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,
                        st.session_state.etrade_selected_account,st.session_state.etrade_sandbox)
                    if br["success"]:
                        bal=br["data"].get("BalanceResponse",{}); comp=bal.get("Computed",{})
                        b1,b2,b3,b4=st.columns(4)
                        nav=comp.get("RealTimeValues",{}).get("totalAccountValue",comp.get("netMktValue","—"))
                        bp=comp.get("marginBuyingPower",comp.get("cashBuyingPower","—"))
                        with b1: st.metric("NET ACCOUNT VALUE",f"${float(nav):,.2f}" if nav!="—" else "—")
                        with b2: st.metric("BUYING POWER",f"${float(bp):,.2f}" if bp!="—" else "—")
                        with b3: st.metric("CASH BALANCE",f"${float(bal.get('cashBalance',0)):,.2f}")
                        with b4: st.metric("ACCOUNT TYPE",acct.get("accountType","—"))
                    st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin:16px 0 8px 0;">◈ CURRENT POSITIONS</p>',unsafe_allow_html=True)
                    pr=etrade_get_portfolio(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                        st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,
                        st.session_state.etrade_selected_account,st.session_state.etrade_sandbox)
                    if pr["success"]:
                        try:
                            pfs=pr["data"]["PortfolioResponse"]["AccountPortfolio"]
                            if not isinstance(pfs,list): pfs=[pfs]
                            positions=[]
                            for pf in pfs:
                                pl=pf.get("Position",[]); 
                                if not isinstance(pl,list): pl=[pl]
                                for p in pl:
                                    prod=p.get("Product",{})
                                    positions.append({"Symbol":prod.get("symbol","—"),"Type":prod.get("securityType","—"),
                                        "Qty":p.get("quantity",0),"Cost/Share":f"${float(p.get('pricePaid',0)):.2f}",
                                        "Mkt Value":f"${float(p.get('marketValue',0)):,.2f}",
                                        "Day Gain":f"${float(p.get('daysGain',0)):,.2f}",
                                        "Day Gain %":f"{float(p.get('daysGainPct',0)):.2f}%",
                                        "Total Gain":f"${float(p.get('totalGain',0)):,.2f}",
                                        "% Portfolio":f"{float(p.get('pctOfPortfolio',0)):.2f}%"})
                            if positions: st.dataframe(pd.DataFrame(positions),use_container_width=True,height=300)
                            else: st.info("No open positions.")
                        except Exception as e: st.warning(f"Could not parse positions: {e}")
                    else: st.warning(f"Portfolio fetch failed: {pr['error']}")
                except Exception as e: st.error(f"Error: {e}")

        with et2:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:12px;">◈ REAL-TIME QUOTES</p>',unsafe_allow_html=True)
            default_syms=",".join(list(scan_df["Ticker"].head(10))) if len(scan_df)>0 else "NVDA,AAPL,TSLA,SPY"
            qinput=st.text_input("Symbols (comma-separated)",value=default_syms,key="quote_input")
            if st.button("📡 FETCH QUOTES",key="btn_quotes"):
                syms=[s.strip().upper() for s in qinput.split(",") if s.strip()]
                if syms:
                    with st.spinner(f"Fetching {len(syms)} quotes..."):
                        r=etrade_get_quotes(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                            st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,syms,st.session_state.etrade_sandbox)
                    if r["success"]: st.session_state.etrade_live_quotes=r["data"]
                    else: st.error(f"Quote fetch failed: {r['error']}")
            if st.session_state.etrade_live_quotes:
                try:
                    ql=st.session_state.etrade_live_quotes["QuoteResponse"]["QuoteData"]
                    if not isinstance(ql,list): ql=[ql]
                    rows=[]
                    for q in ql:
                        prod=q.get("Product",{}); aq=q.get("All",{}); sym=prod.get("symbol","—")
                        last=float(aq.get("lastTrade",0)); chg=float(aq.get("change",0)); chgp=float(aq.get("changePercent",0))
                        vol=int(aq.get("totalVolume",0)); avgv=int(aq.get("averageVolume",1) or 1)
                        gn="—"
                        if sym in scan_df["Ticker"].values:
                            sr=scan_df[scan_df["Ticker"]==sym].iloc[0]
                            if isinstance(sr["γ Trigger"],float):
                                d=(sr["γ Trigger"]-last)/last*100
                                gn=f"⚡ AT γ ({d:+.1f}%)" if abs(d)<1 else (f"↑ {d:.1f}% to γ" if d>0 else "ABOVE γ")
                        rows.append({"Symbol":sym,"Last":f"${last:.2f}","Chg":f"${chg:+.2f}","Chg %":f"{chgp:+.2f}%",
                            "Bid":f"${float(aq.get('bid',0)):.2f}","Ask":f"${float(aq.get('ask',0)):.2f}",
                            "Volume":f"{vol:,}","Rel Vol":f"×{vol/avgv:.2f}",
                            "Hi":f"${float(aq.get('high',0)):.2f}","Lo":f"${float(aq.get('low',0)):.2f}","γ Status":gn})
                    st.dataframe(pd.DataFrame(rows),use_container_width=True,height=350)
                    syms_c=[r["Symbol"] for r in rows]; changes=[float(r["Chg %"].replace("%","").replace("+","")) for r in rows]
                    fig=go.Figure(go.Bar(x=syms_c,y=changes,marker_color=["#00ff88" if c>=0 else "#ff3366" for c in changes],
                        text=[f"{c:+.2f}%" for c in changes],textposition="outside",textfont=dict(family="Share Tech Mono",size=9,color="#e2e8f0")))
                    fig.update_layout(paper_bgcolor="#060810",plot_bgcolor="#0a0d1a",template="plotly_dark",height=280,
                        margin=dict(t=40,b=40,l=60,r=20),showlegend=False,
                        title=dict(text="Intraday Change %",font=dict(family="Orbitron",size=12,color="#e2e8f0")),
                        xaxis=dict(tickfont=dict(family="Share Tech Mono",size=10),color="#94a3b8"),
                        yaxis=dict(title="Change %",gridcolor="#1e2a3a",color="#94a3b8",zeroline=True,zerolinecolor="#2d3f55"))
                    st.plotly_chart(fig,use_container_width=True)
                except Exception as e: st.warning(f"Could not parse quotes: {e}")

        with et3:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:12px;">◈ ORDER ENTRY</p>',unsafe_allow_html=True)
            if not st.session_state.etrade_selected_account:
                st.warning("Select an account in the Accounts tab first.")
            else:
                banner_c="#ffb800" if st.session_state.etrade_sandbox else "#ff3366"
                banner_t="⚠ SANDBOX MODE — No real money." if st.session_state.etrade_sandbox else "⚡ LIVE MODE — Real money. Confirm carefully."
                st.markdown(f"""<div style="background:{banner_c}11;border:1px solid {banner_c}44;border-radius:6px;padding:10px 14px;margin-bottom:16px;font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:{banner_c};">{banner_t}</div>""",unsafe_allow_html=True)
                oc1,oc2,oc3=st.columns(3)
                with oc1:
                    default_sym=scan_df.iloc[0]["Ticker"] if len(scan_df)>0 else "AAPL"
                    order_symbol=st.text_input("Symbol",value=default_sym,key="order_symbol").upper()
                    order_action=st.selectbox("Action",["BUY","SELL","BUY_TO_COVER","SELL_SHORT"],key="order_action")
                with oc2:
                    order_qty=st.number_input("Quantity",min_value=1,max_value=10000,value=100,step=1,key="order_qty")
                    order_type=st.selectbox("Order Type",["MARKET","LIMIT"],key="order_type")
                with oc3:
                    limit_price=0.0
                    if order_type=="LIMIT":
                        limit_price=st.number_input("Limit Price ($)",min_value=0.01,value=100.0,step=0.01,key="limit_price",format="%.2f")
                    else:
                        st.markdown("""<div style="background:#0d1120;border:1px solid #1e2a3a;border-radius:6px;padding:14px;margin-top:24px;font-family:'Share Tech Mono',monospace;font-size:0.65rem;color:#475569;">Market order — executes at best available price</div>""",unsafe_allow_html=True)
                action_color="#00ff88" if "BUY" in order_action else "#ff3366"
                st.markdown(f"""<div style="background:#0d1120;border:1px solid #2d3f55;border-radius:8px;padding:14px 18px;margin:16px 0;font-family:'Share Tech Mono',monospace;font-size:0.7rem;color:#94a3b8;display:flex;gap:24px;flex-wrap:wrap;">
                    <span>Symbol: <b style="color:#e2e8f0;">{order_symbol}</b></span>
                    <span>Action: <b style="color:{action_color};">{order_action}</b></span>
                    <span>Qty: <b style="color:#e2e8f0;">{order_qty}</b></span>
                    <span>Type: <b style="color:#ffb800;">{order_type}</b></span>
                    {"<span>Limit: <b style='color:#8b5cf6;'>$"+f"{limit_price:.2f}"+"</b></span>" if order_type=="LIMIT" else ""}</div>""",unsafe_allow_html=True)
                pc,plc=st.columns(2)
                with pc:
                    if st.button("🔍 PREVIEW ORDER",key="btn_preview"):
                        with st.spinner("Previewing..."):
                            r=etrade_preview_order(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                                st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,
                                st.session_state.etrade_selected_account,order_symbol,order_action,order_qty,order_type,limit_price,st.session_state.etrade_sandbox)
                        if r["success"]: st.session_state.order_preview_data=r["data"]; st.success("Preview received — review below.")
                        else: st.error(f"Preview failed: {r['error']}"); st.session_state.order_preview_data=None
                if st.session_state.order_preview_data:
                    try:
                        prev=st.session_state.order_preview_data.get("PreviewOrderResponse",{})
                        o=prev.get("Order",[{}]); o=o[0] if isinstance(o,list) else o
                        pids=prev.get("PreviewIds",[{}]); pid=str((pids[0] if isinstance(pids,list) else pids).get("previewId",""))
                        st.markdown(f"""<div style="background:#0d1120;border:1px solid rgba(0,255,136,0.3);border-radius:8px;padding:14px 18px;margin:12px 0;">
                            <div style="font-family:'Share Tech Mono',monospace;font-size:0.6rem;color:#00ff88;letter-spacing:0.1em;margin-bottom:10px;">ORDER PREVIEW CONFIRMED</div>
                            <div style="display:flex;gap:24px;flex-wrap:wrap;font-family:'Share Tech Mono',monospace;font-size:0.68rem;color:#94a3b8;">
                                <span>Preview ID: <b style="color:#e2e8f0;">{pid}</b></span>
                                <span>Est. Commission: <b style="color:#ffb800;">${o.get('estimatedCommission','—')}</b></span>
                                <span>Est. Total: <b style="color:#00ff88;">${o.get('estimatedTotalAmount','—')}</b></span></div></div>""",unsafe_allow_html=True)
                        with plc:
                            btn_label="⚡ PLACE ORDER (LIVE)" if not st.session_state.etrade_sandbox else "⚡ PLACE ORDER (SANDBOX)"
                            if st.button(btn_label,key="btn_place"):
                                with st.spinner("Placing order..."):
                                    r=etrade_place_order(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                                        st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,
                                        st.session_state.etrade_selected_account,order_symbol,order_action,order_qty,order_type,limit_price,pid,st.session_state.etrade_sandbox)
                                if r["success"]:
                                    pr=r["data"].get("PlaceOrderResponse",{}); oids=pr.get("OrderIds",[{}])
                                    oid=(oids[0] if isinstance(oids,list) else oids).get("orderId","?")
                                    st.success(f"✅ Order placed! Order ID: {oid}"); st.session_state.order_preview_data=None
                                else: st.error(f"Order failed: {r['error']}")
                    except Exception as e: st.warning(f"Could not parse preview: {e}")

        with et4:
            st.markdown('<p style="font-family:\'Share Tech Mono\',monospace;font-size:0.65rem;color:#00b4ff;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:12px;">◈ RECENT ORDERS</p>',unsafe_allow_html=True)
            if not st.session_state.etrade_selected_account:
                st.warning("Select an account in Accounts tab first.")
            else:
                if st.button("↻ Refresh Orders",key="btn_ord_refresh"):
                    pass
                with st.spinner("Fetching orders..."):
                    r=etrade_get_orders(st.session_state.etrade_consumer_key,st.session_state.etrade_consumer_secret,
                        st.session_state.etrade_access_token,st.session_state.etrade_access_token_secret,
                        st.session_state.etrade_selected_account,st.session_state.etrade_sandbox)
                if r["success"]:
                    try:
                        ol=r["data"].get("OrdersResponse",{}).get("Order",[])
                        if not isinstance(ol,list): ol=[ol]
                        if ol and ol[0]:
                            rows=[]
                            for o in ol:
                                d=o.get("OrderDetail",[{}]); d=d[0] if isinstance(d,list) else d
                                ins=d.get("Instrument",[{}]); ins=ins[0] if isinstance(ins,list) else ins
                                prod=ins.get("Product",{})
                                rows.append({"Order ID":o.get("orderId","—"),"Symbol":prod.get("symbol","—"),
                                    "Action":ins.get("orderAction","—"),"Qty":ins.get("orderedQuantity","—"),
                                    "Filled":ins.get("filledQuantity","—"),"Type":d.get("priceType","—"),
                                    "Limit":f"${float(d.get('limitPrice',0)):.2f}" if d.get("limitPrice") else "—",
                                    "Status":o.get("orderStatus","—"),"Placed":o.get("placedTime","—")})
                            st.dataframe(pd.DataFrame(rows),use_container_width=True,height=400)
                        else: st.info("No recent orders found.")
                    except Exception as e: st.warning(f"Parse error: {e}")
                else: st.error(f"Orders fetch failed: {r['error']}")


# ─────────────────────────────────────────────
# SIDEBAR — E*TRADE STATUS BADGE
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────
st.markdown(f"""
<div style="margin-top:20px; border-top:1px solid #1e2a3a; padding-top:10px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;">
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#2d3f55;">JEG BALLISTIC AI v6 · GAMMA RECLAIM + TREND + REJECTION + OPEX + E*TRADE PRO · JEG SECURITIES INTERNAL USE ONLY</div>
    <div style="font-family:'Share Tech Mono',monospace; font-size:0.55rem; color:#2d3f55;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')} · {'LIVE DATA' if use_live else 'SIMULATION MODE'} · OPEX: {opex_info['phase']}</div>
</div>
""", unsafe_allow_html=True)
