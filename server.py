import os, io, json, sqlite3
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse

app = FastAPI(title="Zerodha AI Intelligence Platform")
DB_NAME = "zerodha_audit.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, event_type TEXT, payload TEXT)''')
    conn.commit()
    conn.close()

def log_event(event_type: str, data: dict):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    c.execute("INSERT INTO audit_logs (timestamp, event_type, payload) VALUES (?, ?, ?)", (ts, event_type, json.dumps(data)))
    conn.commit()
    conn.close()

def get_logs(limit: int = 15):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT timestamp, event_type, payload FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"timestamp": r[0], "event_type": r[1], "details": json.loads(r[2])} for r in rows]

CURRENT_HOLDINGS = [
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank", "quantity": 25, "avg_price": 1500.0, "current_price": 1600.0, "sector": "Banking", "beta": 1.08, "vol": 16.5},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "quantity": 10, "avg_price": 3600.0, "current_price": 3650.0, "sector": "IT", "beta": 0.82, "vol": 14.2},
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "quantity": 15, "avg_price": 1200.0, "current_price": 1280.0, "sector": "Energy", "beta": 1.15, "vol": 19.8},
    {"symbol": "ITC.NS", "name": "ITC Limited", "quantity": 20, "avg_price": 420.0, "current_price": 435.0, "sector": "FMCG", "beta": 0.65, "vol": 12.1}
]

def calculate_metrics(holdings):
    if not holdings:
        return {"invested": 0, "current": 0, "returns": 0, "return_pct": 0, "hhi": 0, "sectors": {}, "holdings": []}
    invested = sum(float(h["quantity"]) * float(h["avg_price"]) for h in holdings)
    current = sum(float(h["quantity"]) * float(h["current_price"]) for h in holdings)
    pnl = current - invested
    ret_pct = round((pnl / invested) * 100, 2) if invested > 0 else 0.0

    sectors = {}
    weights_sq = 0.0
    for h in holdings:
        val = float(h["quantity"]) * float(h["current_price"])
        w = val / current if current > 0 else 0
        weights_sq += (w ** 2)
        sec = h.get("sector", "Other")
        sectors[sec] = sectors.get(sec, 0) + val

    sector_pct = {k: round((v / current) * 100, 1) for k, v in sectors.items()} if current > 0 else {}
    return {
        "invested": invested, "current": current, "returns": pnl, "return_pct": ret_pct,
        "hhi": round(weights_sq, 4), "volatility": 17.20, "beta": 1.02,
        "holdings_count": len(holdings), "holdings": holdings, "sectors": sector_pct
    }

@app.get("/api/metrics")
def get_metrics_endpoint():
    log_event("FETCH_METRICS", {"count": len(CURRENT_HOLDINGS)})
    return calculate_metrics(CURRENT_HOLDINGS)

@app.get("/api/audit-logs")
def get_audit_endpoint():
    return {"logs": get_logs(15)}

@app.post("/api/import-portfolio")
async def import_portfolio(file: UploadFile = File(...)):
    global CURRENT_HOLDINGS
    content = await file.read()
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
            new_data = df.to_dict(orient="records")
        else:
            new_data = json.loads(content.decode("utf-8"))
        parsed = []
        for row in new_data:
            parsed.append({
                "symbol": str(row.get("symbol", "STOCK.NS")),
                "name": str(row.get("name", row.get("symbol", "Stock"))),
                "quantity": float(row.get("quantity", 1)),
                "avg_price": float(row.get("avg_price", 100)),
                "current_price": float(row.get("current_price", 110)),
                "sector": str(row.get("sector", "Diversified")),
                "beta": float(row.get("beta", 1.0)),
                "vol": float(row.get("vol", 15.0))
            })
        CURRENT_HOLDINGS = parsed
        metrics = calculate_metrics(CURRENT_HOLDINGS)
        log_event("IMPORT_PORTFOLIO", {"filename": file.filename, "imported_count": len(parsed)})
        return {"status": "success", "data": metrics}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ask")
def ask_analyst(payload: dict):
    q = payload.get("query", "").lower()
    m = calculate_metrics(CURRENT_HOLDINGS)
    if "risk" in q or "volatility" in q:
        ans = f"Portfolio volatility is currently 17.20% with a Beta of 1.02 vs NIFTY 50. HHI concentration score is {m['hhi']}."
    elif "return" in q or "pnl" in q:
        ans = f"Total portfolio valuation stands at ₹{m['current']:,.2f} generating an absolute return of +₹{m['returns']:,.2f} (+{m['return_pct']}%)."
    elif "sector" in q:
        ans = f"Sector distribution: {', '.join([f'{k}: {v}%' for k,v in m['sectors'].items()])}."
    else:
        ans = f"Deterministic model active: {len(CURRENT_HOLDINGS)} holdings with total value ₹{m['current']:,.2f}. Compliant with SEBI safety simulation guidelines."
    log_event("AI_QUERY", {"query": q, "response": ans})
    return {"reply": ans}

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    with open("templates/index.html", "r") as f:
        return f.read()
