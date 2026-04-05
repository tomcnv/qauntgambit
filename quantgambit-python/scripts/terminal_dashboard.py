#!/usr/bin/env python3
"""
Elegant Terminal Dashboard for QuantGambit Trading Bot

A beautiful, real-time terminal dashboard that displays:
- P&L (realized, unrealized, net)
- Drawdown and equity curve
- Exposure (net/gross)
- Position summary
- Recent trades
- System status (WebSocket connections, data quality)
- Risk state

Uses the QuantGambit API (same as React dashboard) for data.

Usage:
    python scripts/terminal_dashboard.py [--bot-id BOT_ID] [--tenant-id TENANT_ID]
"""

import asyncio
import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import httpx

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.text import Text
    from rich import box
except ImportError:
    print("Please install rich: pip install rich")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# STYLING
# ═══════════════════════════════════════════════════════════════════════════════

COLORS = {
    "profit": "bold green",
    "loss": "bold red",
    "neutral": "dim white",
    "header": "bold cyan",
    "accent": "bold magenta",
    "warning": "bold yellow",
    "success": "bold green",
    "error": "bold red",
    "muted": "dim",
}


def format_pnl(value: float, include_sign: bool = True) -> Text:
    """Format P&L with color coding."""
    if value > 0:
        prefix = "+" if include_sign else ""
        return Text(f"{prefix}${value:,.2f}", style=COLORS["profit"])
    elif value < 0:
        return Text(f"${value:,.2f}", style=COLORS["loss"])
    else:
        return Text(f"${value:,.2f}", style=COLORS["neutral"])


def format_percent(value: float, include_sign: bool = True) -> Text:
    """Format percentage with color coding."""
    if value > 0:
        prefix = "+" if include_sign else ""
        return Text(f"{prefix}{value:.2f}%", style=COLORS["profit"])
    elif value < 0:
        return Text(f"{value:.2f}%", style=COLORS["loss"])
    else:
        return Text(f"{value:.2f}%", style=COLORS["neutral"])


def format_status(status: str) -> Text:
    """Format status indicator."""
    status_map = {
        "ok": ("●", COLORS["success"]),
        "connected": ("●", COLORS["success"]),
        "healthy": ("●", COLORS["success"]),
        "running": ("●", COLORS["success"]),
        "warning": ("●", COLORS["warning"]),
        "stale": ("●", COLORS["warning"]),
        "degraded": ("●", COLORS["warning"]),
        "error": ("●", COLORS["error"]),
        "disconnected": ("●", COLORS["error"]),
        "dead": ("●", COLORS["error"]),
        "down": ("●", COLORS["error"]),
    }
    symbol, style = status_map.get(status.lower(), ("○", COLORS["muted"]))
    return Text(f"{symbol} {status.upper()}", style=style)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CONTAINER
# ═══════════════════════════════════════════════════════════════════════════════

class DashboardData:
    """Container for all dashboard data."""
    
    def __init__(self):
        self.equity: float = 0.0
        self.peak_equity: float = 0.0
        self.realized_pnl: float = 0.0
        self.unrealized_pnl: float = 0.0
        self.fees: float = 0.0
        self.drawdown_pct: float = 0.0
        self.net_exposure: float = 0.0
        self.gross_exposure: float = 0.0
        self.max_exposure: float = 10000.0
        self.positions: List[Dict] = []
        self.recent_trades: List[Dict] = []
        self.pending_orders: int = 0
        self.trades_today: int = 0
        self.win_rate: float = 0.0
        self.avg_trade_pnl: float = 0.0
        self.bot_state: str = "unknown"
        self.risk_status: str = "ok"
        self.pipeline_status: str = "unknown"
        self.last_tick_age: int = 999
        self.symbols: List[str] = []
        self.last_update: datetime = datetime.now(timezone.utc)
        self.ticks_processed: int = 0
        self.decisions_made: int = 0
        self.intents_emitted: int = 0
        self.kill_switch_active: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# API CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class QuantGambitAPI:
    """Client for QuantGambit API (same endpoints as React dashboard)."""
    
    def __init__(self, base_url: str, tenant_id: str, bot_id: str):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.bot_id = bot_id
        self.client = httpx.AsyncClient(timeout=10.0)
    
    def _params(self) -> Dict[str, str]:
        return {"tenant_id": self.tenant_id, "bot_id": self.bot_id}
    
    async def get_live_status(self) -> Dict[str, Any]:
        """Get live status from /api/dashboard/live-status"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/dashboard/live-status",
                params=self._params()
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}
    
    async def get_positions(self) -> List[Dict]:
        """Get positions from /api/dashboard/positions"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/dashboard/positions",
                params=self._params()
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("positions", [])
        except Exception:
            return []
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get metrics from /api/dashboard/metrics"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/dashboard/metrics",
                params=self._params()
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)
        except Exception:
            return {}
    
    async def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution stats from /api/dashboard/execution"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/dashboard/execution",
                params=self._params()
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)
        except Exception:
            return {}
    
    async def get_hot_path_stats(self) -> Dict[str, Any]:
        """Get hot path stats from /api/quant/hot-path/stats"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/quant/hot-path/stats",
                params=self._params()
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}
    
    async def get_pipeline_health(self) -> Dict[str, Any]:
        """Get pipeline health from /api/quant/pipeline/health"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/quant/pipeline/health",
                params=self._params()
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}
    
    async def get_kill_switch_status(self) -> Dict[str, Any]:
        """Get kill switch status from /api/quant/kill-switch/status"""
        try:
            resp = await self.client.get(
                f"{self.base_url}/api/quant/kill-switch/status",
                params=self._params()
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}
    
    async def close(self):
        await self.client.aclose()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

async def fetch_dashboard_data(api: QuantGambitAPI) -> DashboardData:
    """Fetch all dashboard data from the API (parallel requests)."""
    data = DashboardData()
    
    # Fetch all data in parallel
    results = await asyncio.gather(
        api.get_live_status(),
        api.get_positions(),
        api.get_metrics(),
        api.get_execution_stats(),
        api.get_hot_path_stats(),
        api.get_pipeline_health(),
        api.get_kill_switch_status(),
        return_exceptions=True,
    )
    
    live_status = results[0] if not isinstance(results[0], Exception) else {}
    positions = results[1] if not isinstance(results[1], Exception) else []
    metrics = results[2] if not isinstance(results[2], Exception) else {}
    execution = results[3] if not isinstance(results[3], Exception) else {}
    hot_path = results[4] if not isinstance(results[4], Exception) else {}
    pipeline = results[5] if not isinstance(results[5], Exception) else {}
    kill_switch = results[6] if not isinstance(results[6], Exception) else {}
    
    # Parse live status
    if live_status:
        data.bot_state = live_status.get("state", live_status.get("botState", "unknown"))
        health = live_status.get("health", {})
        data.risk_status = health.get("risk_status", "ok")
        
        # Last tick age
        last_tick = health.get("last_tick_time")
        if last_tick:
            try:
                tick_time = datetime.fromisoformat(str(last_tick).replace("Z", "+00:00"))
                data.last_tick_age = int((datetime.now(timezone.utc) - tick_time).total_seconds())
            except:
                pass
    
    # Parse positions
    data.positions = positions[:10]  # Top 10
    data.symbols = list(set(p.get("symbol", "") for p in positions if p.get("quantity", 0) != 0))
    
    # Calculate exposure from positions
    total_long = sum(
        abs(float(p.get("quantity", 0)) * float(p.get("markPrice") or p.get("mark_price") or p.get("entryPrice") or p.get("entry_price") or 0))
        for p in positions if p.get("side", "").upper() in ("LONG", "BUY")
    )
    total_short = sum(
        abs(float(p.get("quantity", 0)) * float(p.get("markPrice") or p.get("mark_price") or p.get("entryPrice") or p.get("entry_price") or 0))
        for p in positions if p.get("side", "").upper() in ("SHORT", "SELL")
    )
    data.net_exposure = total_long - total_short
    data.gross_exposure = total_long + total_short
    data.unrealized_pnl = sum(float(p.get("unrealizedPnl") or p.get("unrealized_pnl") or 0) for p in positions)
    
    # Parse metrics
    if metrics:
        data.equity = float(metrics.get("equity", 0) or 0)
        data.peak_equity = float(metrics.get("peak_equity", data.equity) or data.equity)
        data.realized_pnl = float(metrics.get("realized_pnl", 0) or 0)
        data.fees = float(metrics.get("fees", 0) or 0)
        data.max_exposure = float(metrics.get("max_exposure", 10000) or 10000)
        data.trades_today = int(metrics.get("trades_today", 0) or 0)
        data.win_rate = float(metrics.get("win_rate", 0) or 0)
        
        if data.peak_equity > 0:
            data.drawdown_pct = ((data.peak_equity - data.equity) / data.peak_equity) * 100
    
    # Parse execution stats for recent trades
    if execution:
        data.recent_trades = execution.get("recentFills", execution.get("recent_fills", []))[:8]
        data.pending_orders = int(execution.get("pendingCount", execution.get("pending_count", 0)) or 0)
    
    # Parse hot path stats
    if hot_path:
        data.ticks_processed = int(hot_path.get("ticks_processed", 0) or 0)
        data.decisions_made = int(hot_path.get("decisions_made", 0) or 0)
        data.intents_emitted = int(hot_path.get("intents_emitted", 0) or 0)
    
    # Parse pipeline health
    if pipeline:
        data.pipeline_status = pipeline.get("overall_status", "unknown")
    
    # Parse kill switch
    if kill_switch:
        status = kill_switch.get("status", kill_switch)
        data.kill_switch_active = status.get("is_active", False)
    
    data.last_update = datetime.now(timezone.utc)
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

def create_header(data: DashboardData, bot_id: str) -> Panel:
    """Create the header panel with bot info and status."""
    heartbeat = "ok" if data.last_tick_age < 5 else "stale" if data.last_tick_age < 30 else "dead"
    
    status_line = Text()
    status_line.append("  BOT: ", style="dim")
    status_line.append(bot_id[:20], style=COLORS["accent"])
    status_line.append("  │  ", style="dim")
    status_line.append("STATE: ", style="dim")
    status_line.append(data.bot_state.upper(), style=COLORS["success"] if data.bot_state == "running" else COLORS["warning"])
    status_line.append("  │  ", style="dim")
    status_line.append("HEARTBEAT: ", style="dim")
    status_line.append_text(format_status(heartbeat))
    status_line.append("  │  ", style="dim")
    status_line.append("PIPELINE: ", style="dim")
    status_line.append_text(format_status(data.pipeline_status))
    status_line.append("  │  ", style="dim")
    status_line.append("KILL: ", style="dim")
    if data.kill_switch_active:
        status_line.append("ACTIVE", style=COLORS["error"])
    else:
        status_line.append("OFF", style=COLORS["success"])
    
    return Panel(
        status_line,
        title="[bold cyan]⚡ QUANTGAMBIT LIVE TRADING[/bold cyan]",
        subtitle=f"[dim]Updated: {data.last_update.strftime('%H:%M:%S')} UTC[/dim]",
        border_style="cyan",
        box=box.DOUBLE,
    )


def create_pnl_panel(data: DashboardData) -> Panel:
    """Create the P&L summary panel."""
    net_pnl = data.realized_pnl + data.unrealized_pnl - data.fees
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim", width=12)
    table.add_column("Value", justify="right", width=14)
    
    table.add_row("Realized", format_pnl(data.realized_pnl))
    table.add_row("Unrealized", format_pnl(data.unrealized_pnl))
    table.add_row("Fees", Text(f"-${abs(data.fees):,.2f}", style="dim red"))
    table.add_row("─" * 10, "─" * 12)
    table.add_row(Text("NET P&L", style="bold"), format_pnl(net_pnl))
    
    return Panel(table, title="[bold green]💰 TODAY'S P&L[/bold green]", border_style="green", box=box.ROUNDED)


def create_equity_panel(data: DashboardData) -> Panel:
    """Create the equity and drawdown panel."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim", width=12)
    table.add_column("Value", justify="right", width=14)
    
    table.add_row("Equity", Text(f"${data.equity:,.2f}", style="bold white"))
    table.add_row("Peak", Text(f"${data.peak_equity:,.2f}", style="dim"))
    table.add_row("Drawdown", format_percent(-data.drawdown_pct, include_sign=False))
    
    return Panel(table, title="[bold blue]📊 EQUITY[/bold blue]", border_style="blue", box=box.ROUNDED)


def create_exposure_panel(data: DashboardData) -> Panel:
    """Create the exposure panel."""
    exposure_pct = (data.gross_exposure / data.max_exposure * 100) if data.max_exposure > 0 else 0
    
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim", width=12)
    table.add_column("Value", justify="right", width=14)
    
    net_style = COLORS["profit"] if data.net_exposure >= 0 else COLORS["loss"]
    table.add_row("Net", Text(f"${data.net_exposure:,.0f}", style=net_style))
    table.add_row("Gross", Text(f"${data.gross_exposure:,.0f}", style="white"))
    table.add_row("Utilization", Text(f"{exposure_pct:.0f}%", style="yellow" if exposure_pct > 60 else "dim"))
    
    return Panel(table, title="[bold yellow]⚖️ EXPOSURE[/bold yellow]", border_style="yellow", box=box.ROUNDED)


def create_stats_panel(data: DashboardData) -> Panel:
    """Create the trading stats panel."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim", width=12)
    table.add_column("Value", justify="right", width=14)
    
    table.add_row("Trades Today", Text(str(data.trades_today), style="bold"))
    table.add_row("Win Rate", Text(f"{data.win_rate:.1f}%", style=COLORS["profit"] if data.win_rate > 50 else COLORS["loss"]))
    table.add_row("Positions", Text(str(len(data.positions)), style="cyan"))
    table.add_row("Pending", Text(str(data.pending_orders), style="dim"))
    
    return Panel(table, title="[bold magenta]📈 STATS[/bold magenta]", border_style="magenta", box=box.ROUNDED)


def create_positions_table(data: DashboardData) -> Panel:
    """Create the positions table."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", row_styles=["", "dim"])
    
    table.add_column("Symbol", style="bold", width=12)
    table.add_column("Side", width=6)
    table.add_column("Qty", justify="right", width=10)
    table.add_column("Entry", justify="right", width=12)
    table.add_column("Mark", justify="right", width=12)
    table.add_column("P&L", justify="right", width=12)
    
    if not data.positions:
        table.add_row(Text("No open positions", style="dim italic"), "", "", "", "", "")
    else:
        for pos in data.positions[:6]:
            side = pos.get("side", "").upper()
            side_style = COLORS["profit"] if side in ("LONG", "BUY") else COLORS["loss"]
            pnl = float(pos.get("unrealizedPnl") or pos.get("unrealized_pnl") or 0)
            qty = float(pos.get("quantity", 0))
            entry = float(pos.get("entryPrice") or pos.get("entry_price") or 0)
            mark = float(pos.get("markPrice") or pos.get("mark_price") or entry)
            
            table.add_row(
                pos.get("symbol", "")[:12],
                Text(side[:4], style=side_style),
                f"{qty:.4f}",
                f"${entry:,.2f}",
                f"${mark:,.2f}",
                format_pnl(pnl),
            )
    
    return Panel(table, title="[bold cyan]📋 POSITIONS[/bold cyan]", border_style="cyan", box=box.ROUNDED)


def create_trades_table(data: DashboardData) -> Panel:
    """Create the recent trades table."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold green", row_styles=["", "dim"])
    
    table.add_column("Time", width=8)
    table.add_column("Symbol", width=10)
    table.add_column("Side", width=5)
    table.add_column("Qty", justify="right", width=8)
    table.add_column("Price", justify="right", width=10)
    table.add_column("P&L", justify="right", width=10)
    
    if not data.recent_trades:
        table.add_row(Text("No recent trades", style="dim italic"), "", "", "", "", "")
    else:
        for trade in data.recent_trades[:8]:
            ts = trade.get("timestamp") or trade.get("time")
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=timezone.utc)
                    time_str = dt.strftime("%H:%M:%S")
                except:
                    time_str = "—"
            else:
                time_str = "—"
            
            side = trade.get("side", "").upper()
            side_style = COLORS["profit"] if side in ("BUY", "LONG") else COLORS["loss"]
            pnl = float(trade.get("pnl", 0) or 0)
            qty = float(trade.get("quantity") or trade.get("qty") or 0)
            price = float(trade.get("price", 0) or 0)
            
            table.add_row(
                time_str,
                str(trade.get("symbol", ""))[:10],
                Text(side[:4], style=side_style),
                f"{qty:.4f}",
                f"${price:,.2f}",
                format_pnl(pnl),
            )
    
    return Panel(table, title="[bold green]🔄 RECENT TRADES[/bold green]", border_style="green", box=box.ROUNDED)


def create_pipeline_panel(data: DashboardData) -> Panel:
    """Create the pipeline stats panel."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Label", style="dim", width=14)
    table.add_column("Value", justify="right", width=12)
    
    table.add_row("Ticks", Text(f"{data.ticks_processed:,}", style="cyan"))
    table.add_row("Decisions", Text(f"{data.decisions_made:,}", style="yellow"))
    table.add_row("Intents", Text(f"{data.intents_emitted:,}", style="green"))
    table.add_row("Symbols", Text(str(len(data.symbols)), style="magenta"))
    
    return Panel(table, title="[bold cyan]🔧 PIPELINE[/bold cyan]", border_style="cyan", box=box.ROUNDED)


# ═══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

def create_layout() -> Layout:
    """Create the dashboard layout."""
    layout = Layout()
    
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )
    
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2),
    )
    
    layout["left"].split_column(
        Layout(name="pnl", size=9),
        Layout(name="equity", size=7),
        Layout(name="exposure", size=7),
        Layout(name="stats", size=8),
    )
    
    layout["right"].split_column(
        Layout(name="positions", ratio=1),
        Layout(name="trades", ratio=1),
        Layout(name="pipeline", size=8),
    )
    
    return layout


def render_dashboard(data: DashboardData, bot_id: str) -> Layout:
    """Render the complete dashboard."""
    layout = create_layout()
    
    layout["header"].update(create_header(data, bot_id))
    layout["pnl"].update(create_pnl_panel(data))
    layout["equity"].update(create_equity_panel(data))
    layout["exposure"].update(create_exposure_panel(data))
    layout["stats"].update(create_stats_panel(data))
    layout["positions"].update(create_positions_table(data))
    layout["trades"].update(create_trades_table(data))
    layout["pipeline"].update(create_pipeline_panel(data))
    layout["footer"].update(Text("  Press Ctrl+C to exit  │  Refreshing every 2s  │  Using QuantGambit API", style="dim", justify="center"))
    
    return layout


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    # Hardcoded defaults from running PM2 instance
    DEFAULT_TENANT_ID = "11111111-1111-1111-1111-111111111111"
    DEFAULT_BOT_ID = "bf167763-fee1-4f11-ab9a-6fddadf125de"
    
    parser = argparse.ArgumentParser(description="QuantGambit Terminal Dashboard")
    parser.add_argument("--bot-id", default=os.getenv("BOT_ID", DEFAULT_BOT_ID), help="Bot ID to monitor")
    parser.add_argument("--tenant-id", default=os.getenv("TENANT_ID", DEFAULT_TENANT_ID), help="Tenant ID")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:3002"), help="API base URL")
    parser.add_argument("--refresh", type=float, default=2.0, help="Refresh interval in seconds")
    args = parser.parse_args()
    
    bot_id = args.bot_id
    
    console = Console()
    console.print(f"[cyan]Connecting to QuantGambit API at {args.api_url}...[/cyan]")
    console.print(f"[cyan]Bot ID: {bot_id}[/cyan]")
    
    api = QuantGambitAPI(args.api_url, args.tenant_id, bot_id)
    
    # Test connection
    try:
        test_data = await api.get_live_status()
        if test_data:
            console.print("[green]Connected! Starting dashboard...[/green]")
        else:
            console.print("[yellow]Warning: API returned empty response, but continuing...[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not connect to API ({e}), but continuing...[/yellow]")
    
    try:
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while True:
                try:
                    data = await fetch_dashboard_data(api)
                    layout = render_dashboard(data, bot_id)
                    live.update(layout)
                except Exception as e:
                    error_panel = Panel(
                        Text(f"Error fetching data: {e}", style="red"),
                        title="[red]ERROR[/red]",
                        border_style="red",
                    )
                    live.update(error_panel)
                
                await asyncio.sleep(args.refresh)
                
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
