"""
Single-page monitoring dashboard for Moon Dev trading agents.

This FastAPI app surfaces:
- Active exchange, trading mode, and risk guardrails
- Latest portfolio balance checkpoints
- Recent sentiment, funding, liquidation, and open interest stats
- Current portfolio allocations (if present)

Run locally:
    python src/scripts/trading_dashboard.py
Then open http://localhost:8000 for the dashboard UI.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src import config
from src.agents import trading_agent


data_dir = Path("src/data")
app = FastAPI(title="Moon Dev Trading Dashboard")


def parse_timestamp(raw: str) -> Optional[datetime]:
    """Parse timestamps that may be ISO or space separated."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def parse_float(value: str) -> Optional[float]:
    """Convert numeric-looking strings to floats."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_last_row(csv_path: Path) -> Optional[Dict[str, str]]:
    """Return the final row of a CSV file as a dict."""
    if not csv_path.exists():
        return None

    last_row: Optional[Dict[str, str]] = None
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            last_row = row
    return last_row


def get_balance_summary() -> Optional[Dict[str, Any]]:
    balance_path = data_dir / "portfolio_balance.csv"
    if not balance_path.exists():
        return None

    rows: List[Dict[str, str]] = []
    with balance_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows.extend(reader)

    if not rows:
        return None

    def sort_key(row: Dict[str, str]) -> datetime:
        ts = parse_timestamp(row.get("timestamp", ""))
        return ts or datetime.min

    rows.sort(key=sort_key)
    latest = rows[-1]
    previous = rows[-2] if len(rows) > 1 else None

    latest_balance = parse_float(latest.get("balance"))
    latest_ts = parse_timestamp(latest.get("timestamp", ""))

    change = None
    hours_since_previous = None
    if previous:
        prev_balance = parse_float(previous.get("balance"))
        prev_ts = parse_timestamp(previous.get("timestamp", ""))
        if prev_balance is not None and latest_balance is not None:
            change = latest_balance - prev_balance
        if latest_ts and prev_ts:
            hours_since_previous = (latest_ts - prev_ts).total_seconds() / 3600

    return {
        "latest_balance": latest_balance,
        "latest_timestamp": latest_ts.isoformat() if latest_ts else None,
        "change_from_previous": change,
        "hours_since_previous": hours_since_previous,
    }


def get_sentiment_snapshot() -> Optional[Dict[str, Any]]:
    row = read_last_row(data_dir / "sentiment_history.csv")
    if not row:
        return None

    return {
        "timestamp": row.get("timestamp"),
        "sentiment_score": parse_float(row.get("sentiment_score")),
        "num_tweets": parse_float(row.get("num_tweets")),
    }


def get_funding_snapshot() -> Optional[Dict[str, Any]]:
    row = read_last_row(data_dir / "funding_history.csv")
    if not row:
        return None

    funding: Dict[str, Dict[str, Optional[float]]] = {}
    for key, value in row.items():
        if "_funding_rate" in key:
            symbol = key.replace("_funding_rate", "")
            funding.setdefault(symbol, {})["funding_rate"] = parse_float(value)
        elif "_annual_rate" in key:
            symbol = key.replace("_annual_rate", "")
            funding.setdefault(symbol, {})["annual_rate"] = parse_float(value)

    return {
        "timestamp": row.get("event_time") or row.get("timestamp"),
        "funding": funding,
    }


def get_liquidation_snapshot() -> Optional[Dict[str, Any]]:
    row = read_last_row(data_dir / "liquidation_history.csv")
    if not row:
        return None

    return {
        "timestamp": row.get("timestamp"),
        "long_size": parse_float(row.get("long_size")),
        "short_size": parse_float(row.get("short_size")),
        "total_size": parse_float(row.get("total_size")),
    }


def get_open_interest_snapshot() -> Optional[Dict[str, Any]]:
    row = read_last_row(data_dir / "oi_history.csv")
    if not row:
        return None

    return {
        "timestamp": row.get("timestamp"),
        "btc_oi": parse_float(row.get("btc_oi")),
        "eth_oi": parse_float(row.get("eth_oi")),
        "total_oi": parse_float(row.get("total_oi")),
        "btc_change_pct": parse_float(row.get("btc_change_pct")),
        "eth_change_pct": parse_float(row.get("eth_change_pct")),
        "total_change_pct": parse_float(row.get("total_change_pct")),
    }


def get_allocation_snapshot() -> Optional[List[Dict[str, Any]]]:
    alloc_path = data_dir / "current_allocation.csv"
    if not alloc_path.exists():
        return None

    allocations: List[Dict[str, Any]] = []
    with alloc_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            allocations.append(
                {
                    "token": row.get("token"),
                    "allocation": parse_float(row.get("allocation")),
                    "timestamp": row.get("timestamp"),
                }
            )
    return allocations or None


def get_config_snapshot() -> Dict[str, Any]:
    return {
        "exchange": config.EXCHANGE,
        "risk": {
            "cash_buffer_pct": config.CASH_PERCENTAGE,
            "max_position_pct": config.MAX_POSITION_PERCENTAGE,
            "max_loss_usd": config.MAX_LOSS_USD,
            "max_gain_usd": config.MAX_GAIN_USD,
            "min_balance_usd": config.MINIMUM_BALANCE_USD,
            "use_percentage_limits": config.USE_PERCENTAGE,
        },
        "trading": {
            "use_swarm_mode": trading_agent.USE_SWARM_MODE,
            "long_only": trading_agent.LONG_ONLY,
            "leverage": trading_agent.LEVERAGE,
            "symbols": trading_agent.SYMBOLS,
            "monitored_tokens": trading_agent.MONITORED_TOKENS,
            "sleep_between_runs_minutes": trading_agent.SLEEP_BETWEEN_RUNS_MINUTES,
            "data_timeframe": trading_agent.DATA_TIMEFRAME,
            "days_of_history": trading_agent.DAYSBACK_4_DATA,
        },
    }


def get_file_freshness() -> List[Dict[str, Any]]:
    tracked_files = [
        "portfolio_balance.csv",
        "sentiment_history.csv",
        "funding_history.csv",
        "liquidation_history.csv",
        "oi_history.csv",
        "current_allocation.csv",
    ]
    freshness: List[Dict[str, Any]] = []

    for filename in tracked_files:
        path = data_dir / filename
        if not path.exists():
            freshness.append({"name": filename, "exists": False, "last_updated": None})
            continue

        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        freshness.append(
            {
                "name": filename,
                "exists": True,
                "last_updated": mtime.isoformat(),
            }
        )
    return freshness


def build_dashboard_payload() -> Dict[str, Any]:
    return {
        "config": get_config_snapshot(),
        "balance": get_balance_summary(),
        "sentiment": get_sentiment_snapshot(),
        "funding": get_funding_snapshot(),
        "liquidations": get_liquidation_snapshot(),
        "open_interest": get_open_interest_snapshot(),
        "allocations": get_allocation_snapshot(),
        "data_freshness": get_file_freshness(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Moon Dev Trading Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --card-bg: #111827;
      --panel-bg: #0b1220;
      --accent: #22d3ee;
      --text: #e5e7eb;
      --muted: #9ca3af;
    }
    body {
      margin: 0;
      font-family: \"Inter\", system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
      background: radial-gradient(circle at 10% 20%, rgba(34,211,238,0.12), transparent 25%),
                  radial-gradient(circle at 90% 10%, rgba(14,165,233,0.14), transparent 20%),
                  #030712;
      color: var(--text);
      min-height: 100vh;
    }
    header {
      padding: 24px 32px 8px;
    }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0.2px; }
    p.subtitle { margin: 6px 0 0; color: var(--muted); }
    .grid { display: grid; gap: 16px; padding: 0 32px 32px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
    .card {
      background: var(--card-bg);
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 14px;
      padding: 16px 18px;
      box-shadow: 0 20px 40px rgba(0,0,0,0.35);
    }
    .card h2 { margin: 0 0 6px; font-size: 16px; letter-spacing: 0.3px; }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; background: rgba(34,211,238,0.15); color: var(--text); font-size: 12px; }
    .muted { color: var(--muted); font-size: 13px; }
    .value { font-size: 22px; font-weight: 700; margin: 4px 0 2px; }
    .split { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px; }
    .table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
    .table th, .table td { padding: 6px 4px; text-align: left; color: var(--muted); }
    .table th { color: var(--text); font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.08); }
    .tag { padding: 3px 8px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); display: inline-block; margin: 3px 6px 3px 0; font-size: 12px; }
    footer { color: var(--muted); padding: 0 32px 24px; font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <h1>Moon Dev Trading Dashboard</h1>
    <p class=\"subtitle\">Single-page view of trading posture, risk rails, and market telemetry.</p>
  </header>

  <div class=\"grid\" id=\"cards\"></div>
  <div class=\"grid\" id=\"tables\"></div>
  <footer id=\"footer\"></footer>

<script>
async function loadDashboard() {
  const cards = document.getElementById('cards');
  const tables = document.getElementById('tables');
  const footer = document.getElementById('footer');
  cards.innerHTML = '<div class="card">Loading...</div>';
  tables.innerHTML = '';
  footer.textContent = '';

  const response = await fetch('/api/dashboard-data');
  const data = await response.json();
  cards.innerHTML = '';

  const cfg = data.config || {};
  const trading = cfg.trading || {};
  const risk = cfg.risk || {};

  cards.insertAdjacentHTML('beforeend', `
    <div class="card">
      <h2>Exchange & Modes</h2>
      <div class="value">${cfg.exchange?.toUpperCase?.() || '—'}</div>
      <div class="pill">${trading.use_swarm_mode ? 'Swarm Consensus' : 'Single Model'}</div>
      <div class="muted">${trading.long_only ? 'Long-only' : 'Long & Short'} • Leverage ${trading.leverage ?? '—'}x</div>
    </div>
  `);

  const balance = data.balance;
  cards.insertAdjacentHTML('beforeend', `
    <div class="card">
      <h2>Portfolio Balance</h2>
      <div class="value">${balance?.latest_balance?.toFixed?.(2) ? `$${balance.latest_balance.toFixed(2)}` : 'No data'}</div>
      <div class="muted">Updated: ${balance?.latest_timestamp || '—'}</div>
      <div class="muted">Δ vs previous: ${balance?.change_from_previous?.toFixed?.(2) ?? '—'} (${balance?.hours_since_previous?.toFixed?.(1) ?? '—'} hrs apart)</div>
    </div>
  `);

  cards.insertAdjacentHTML('beforeend', `
    <div class="card">
      <h2>Risk Rails</h2>
      <div class="split">
        <div><div class="muted">Cash Buffer</div><div class="value">${risk.cash_buffer_pct ?? '—'}%</div></div>
        <div><div class="muted">Max Position</div><div class="value">${risk.max_position_pct ?? '—'}%</div></div>
        <div><div class="muted">Min Balance</div><div class="value">${risk.min_balance_usd ? '$'+risk.min_balance_usd : '—'}</div></div>
        <div><div class="muted">P&L Guardrail</div><div class="value">±${risk.max_loss_usd ?? '—'}/$${risk.max_gain_usd ?? '—'}</div></div>
      </div>
    </div>
  `);

  const sentiment = data.sentiment;
  cards.insertAdjacentHTML('beforeend', `
    <div class="card">
      <h2>Sentiment</h2>
      <div class="value">${sentiment?.sentiment_score?.toFixed?.(3) ?? '—'}</div>
      <div class="muted">Tweets analyzed: ${sentiment?.num_tweets ?? '—'}</div>
      <div class="muted">Last updated: ${sentiment?.timestamp || '—'}</div>
    </div>
  `);

  const funding = data.funding;
  const fundingRows = Object.entries(funding?.funding || {}).slice(0, 6).map(([sym, vals]) => `
    <tr><td>${sym}</td><td>${vals.funding_rate ?? '—'}</td><td>${vals.annual_rate ?? '—'}</td></tr>`).join('');
  tables.insertAdjacentHTML('beforeend', `
    <div class="card" style="grid-column: span 2; min-width: 320px;">
      <h2>Funding Rates</h2>
      <div class="muted">${funding?.timestamp || 'No timestamp'}</div>
      <table class="table"><thead><tr><th>Symbol</th><th>Funding</th><th>Annualized</th></tr></thead><tbody>${fundingRows || '<tr><td colspan="3">No data</td></tr>'}</tbody></table>
    </div>
  `);

  const liq = data.liquidations;
  tables.insertAdjacentHTML('beforeend', `
    <div class="card">
      <h2>Liquidations</h2>
      <div class="value">${liq?.total_size ? '$' + liq.total_size.toLocaleString() : '—'}</div>
      <div class="muted">Long: ${liq?.long_size ?? '—'} • Short: ${liq?.short_size ?? '—'}</div>
      <div class="muted">${liq?.timestamp || 'No timestamp'}</div>
    </div>
  `);

  const oi = data.open_interest;
  tables.insertAdjacentHTML('beforeend', `
    <div class="card">
      <h2>Open Interest</h2>
      <div class="value">${oi?.total_oi ? '$' + oi.total_oi.toLocaleString() : '—'}</div>
      <div class="muted">BTC: ${oi?.btc_oi ?? '—'} (${oi?.btc_change_pct ?? '—'}%)</div>
      <div class="muted">ETH: ${oi?.eth_oi ?? '—'} (${oi?.eth_change_pct ?? '—'}%)</div>
      <div class="muted">${oi?.timestamp || 'No timestamp'}</div>
    </div>
  `);

  const alloc = data.allocations || [];
  const allocRows = alloc.map(item => `
    <tr><td>${item.token}</td><td>${item.allocation ?? '—'}%</td><td>${item.timestamp || '—'}</td></tr>`).join('');
  tables.insertAdjacentHTML('beforeend', `
    <div class="card" style="grid-column: span 2; min-width: 320px;">
      <h2>Current Allocation</h2>
      <table class="table"><thead><tr><th>Token</th><th>Allocation %</th><th>Timestamp</th></tr></thead><tbody>${allocRows || '<tr><td colspan="3">No allocation records</td></tr>'}</tbody></table>
    </div>
  `);

  tables.insertAdjacentHTML('beforeend', `
    <div class="card" style="grid-column: span 2;">
      <h2>Data Freshness</h2>
      <div class="muted">Shows whether supporting CSVs are present and when they were last touched.</div>
      <div>
        ${(data.data_freshness || []).map(item => `
          <span class="tag">${item.name}: ${item.exists ? (item.last_updated || 'present') : 'missing'}</span>
        `).join('')}
      </div>
    </div>
  `);

  const tokens = (trading.monitored_tokens || []).map(t => `<span class="tag">${t}</span>`).join('');
  const symbols = (trading.symbols || []).map(s => `<span class="tag">${s}</span>`).join('');

  tables.insertAdjacentHTML('beforeend', `
    <div class="card" style="grid-column: span 2;">
      <h2>Watched Assets</h2>
      <div class="muted">Solana tokens</div>
      <div>${tokens || 'None configured'}</div>
      <div class="muted" style="margin-top:8px;">Perp symbols</div>
      <div>${symbols || 'None configured'}</div>
    </div>
  `);

  footer.textContent = `Last refreshed ${new Date(data.generated_at || Date.now()).toLocaleString()} • Auto-refreshes every 30s`;
}

loadDashboard();
setInterval(loadDashboard, 30000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


@app.get("/api/dashboard-data")
async def dashboard_data() -> Dict[str, Any]:
    return build_dashboard_payload()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.scripts.trading_dashboard:app", host="0.0.0.0", port=8000, reload=False)
