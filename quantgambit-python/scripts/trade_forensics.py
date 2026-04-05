#!/usr/bin/env python3
"""
Trade Forensics Tool - Analyze losing trades to understand decision-making.

This script queries the database for recent losing trades and generates detailed
forensics reports showing:
- What market conditions the bot saw at entry
- Why it decided to enter
- Why it allocated the size it did
- Why it exited when it did

Usage:
    python scripts/trade_forensics.py --limit 10
    python scripts/trade_forensics.py --symbol BTCUSDT --limit 20
    python scripts/trade_forensics.py --output-dir .kiro/trade-forensics
"""

import asyncio
import asyncpg
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from quantgambit.observability.logger import log_info, log_warning


def _read_dotenv_value(key: str) -> Optional[str]:
    """Best-effort .env reader for single key."""
    try:
        for line in Path(".env").read_text().splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            if not line.startswith(f"{key}="):
                continue
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def _env_value(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key) or _read_dotenv_value(key) or default


async def get_db_pool() -> asyncpg.Pool:
    """Create database connection pool."""
    timescale_url = _env_value("BOT_TIMESCALE_URL")
    if timescale_url:
        return await asyncpg.create_pool(
            timescale_url,
            min_size=1,
            max_size=5,
            timeout=10.0,
        )
    host = _env_value("BOT_DB_HOST", _env_value("DB_HOST", "localhost"))
    port = _env_value("BOT_DB_PORT", "5432")
    name = _env_value("BOT_DB_NAME", "platform_db")
    user = _env_value("BOT_DB_USER", "platform")
    password = _env_value("BOT_DB_PASSWORD", "platform_pw")
    
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{name}"
    
    pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=5,
        timeout=10.0,
    )
    
    return pool


async def query_losing_trades(
    pool: asyncpg.Pool,
    tenant_id: str,
    bot_id: str,
    symbol: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Query recent losing trades from position_events table."""
    
    query = """
    SELECT 
        ts,
        payload
    FROM position_events
    WHERE tenant_id = $1 
      AND bot_id = $2
      AND (payload->>'event_type') = 'closed'
      AND COALESCE((payload->>'net_pnl')::numeric, (payload->>'realized_pnl')::numeric) < 0
    """
    
    params = [tenant_id, bot_id]
    
    if symbol:
        query += " AND (payload->>'symbol') = $3"
        params.append(symbol)
        query += " ORDER BY ts DESC LIMIT $4"
        params.append(limit)
    else:
        query += " ORDER BY ts DESC LIMIT $3"
        params.append(limit)
    
    rows = await pool.fetch(query, *params)
    
    trades = []
    for row in rows:
        payload = row['payload']
        if isinstance(payload, str):
            payload = json.loads(payload)
        
        trade = {
            'timestamp': row['ts'],
            'symbol': payload.get('symbol'),
            'side': payload.get('side'),
            'size': payload.get('size'),
            'entry_price': payload.get('entry_price'),
            'exit_price': payload.get('exit_price'),
            'realized_pnl': payload.get('realized_pnl'),
            'net_pnl': payload.get('net_pnl'),
            'gross_pnl': payload.get('gross_pnl'),
            'realized_pnl_pct': payload.get('realized_pnl_pct'),
            'fee_usd': payload.get('fee_usd'),
            'entry_fee_usd': payload.get('entry_fee_usd'),
            'total_fees_usd': payload.get('total_fees_usd'),
            'hold_time_sec': payload.get('hold_time_sec'),
            'close_reason': payload.get('closed_by') or payload.get('close_reason'),
            'strategy_id': payload.get('strategy_id'),
            'profile_id': payload.get('profile_id'),
            'mfe_pct': payload.get('mfe_pct'),
            'mae_pct': payload.get('mae_pct'),
            'signal_strength': payload.get('signal_strength'),
            'signal_confidence': payload.get('signal_confidence'),
        }
        
        trades.append(trade)
    
    return trades


async def query_entry_context(
    pool: asyncpg.Pool,
    tenant_id: str,
    bot_id: str,
    symbol: str,
    side: str,
    entry_timestamp: datetime,
) -> Optional[Dict[str, Any]]:
    """Query entry context from order_intents table."""
    
    # Search for order intent within 60 seconds of entry
    query = """
    SELECT 
        snapshot_metrics,
        entry_price,
        stop_loss,
        take_profit,
        strategy_id,
        profile_id,
        size
    FROM order_intents
    WHERE tenant_id = $1
      AND bot_id = $2
      AND symbol = $3
      AND side = $4
      AND created_at BETWEEN ($5::timestamptz - INTERVAL '60 seconds') AND ($5::timestamptz + INTERVAL '60 seconds')
    ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - $5)))
    LIMIT 1
    """
    
    row = await pool.fetchrow(query, tenant_id, bot_id, symbol, side, entry_timestamp)
    
    if not row:
        return None
    
    snapshot_metrics = row['snapshot_metrics']
    if isinstance(snapshot_metrics, str):
        snapshot_metrics = json.loads(snapshot_metrics)
    
    return {
        'snapshot_metrics': snapshot_metrics or {},
        'entry_price': float(row['entry_price']) if row['entry_price'] else None,
        'stop_loss': float(row['stop_loss']) if row['stop_loss'] else None,
        'take_profit': float(row['take_profit']) if row['take_profit'] else None,
        'strategy_id': row['strategy_id'],
        'profile_id': row['profile_id'],
        'size': float(row['size']) if row['size'] else None,
    }


def generate_forensics_report(
    trade: Dict[str, Any],
    entry_context: Optional[Dict[str, Any]],
) -> str:
    """Generate detailed forensics report for a single trade."""
    
    symbol = trade['symbol']
    side = trade['side']
    timestamp = trade['timestamp']
    
    # Format timestamp
    if isinstance(timestamp, datetime):
        ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')
    else:
        ts_str = str(timestamp)
    
    # Format values with proper None handling
    entry_price_str = f"${trade['entry_price']:.2f}" if trade['entry_price'] else 'N/A'
    exit_price_str = f"${trade['exit_price']:.2f}" if trade['exit_price'] else 'N/A'
    fee_str = f"${trade['fee_usd']:.2f}" if trade['fee_usd'] else 'N/A'
    mfe_str = f"{trade['mfe_pct']:.2f}%" if trade['mfe_pct'] is not None else 'N/A'
    mae_str = f"{trade['mae_pct']:.2f}%" if trade['mae_pct'] is not None else 'N/A'
    confidence_str = f"{trade['signal_confidence']:.2f}" if trade['signal_confidence'] is not None else 'N/A'
    
    net_pnl = trade.get('net_pnl') if trade.get('net_pnl') is not None else trade.get('realized_pnl')
    gross_pnl = trade.get('gross_pnl')
    total_fees = trade.get('total_fees_usd')
    if total_fees is None:
        exit_fee = trade.get('fee_usd') or 0
        entry_fee = trade.get('entry_fee_usd') or 0
        total_fees = (exit_fee + entry_fee) if (exit_fee or entry_fee) else None
    report = f"""# Trade Forensics Report: {symbol} {side.upper()} @ {ts_str}

## Trade Summary
- **Symbol:** {symbol}
- **Side:** {side.upper()}
- **Entry Price:** {entry_price_str}
- **Exit Price:** {exit_price_str}
- **Realized PnL (Net):** ${net_pnl:.2f} ({trade['realized_pnl_pct']:.2f}%)
- **Hold Time:** {trade['hold_time_sec']:.0f} seconds ({trade['hold_time_sec']/60:.1f} minutes)
- **Strategy:** {trade['strategy_id'] or 'N/A'}
- **Profile:** {trade['profile_id'] or 'N/A'}
- **Close Reason:** {trade['close_reason'] or 'N/A'}
- **Fee (Exit):** {fee_str}
"""
    if total_fees is not None:
        report += f"- **Total Fees:** ${total_fees:.2f}\n"
    if gross_pnl is not None:
        report += f"- **Gross PnL:** ${gross_pnl:.2f}\n"
    report += """

## Performance Metrics
- **MFE (Max Favorable Excursion):** {mfe_str}
- **MAE (Max Adverse Excursion):** {mae_str}
- **Signal Strength:** {trade['signal_strength'] or 'N/A'}
- **Signal Confidence:** {confidence_str}

"""
    
    if not entry_context:
        report += """## Entry Context
⚠️ **No entry context found** - order intent not found in database within 60 seconds of entry.

"""
        return report
    
    metrics = entry_context.get('snapshot_metrics', {})
    
    # Entry Context Section
    report += f"""## Entry Context (What the bot saw)

### Market Conditions
- **Price:** ${metrics.get('price', 'N/A')}
- **POC Price:** ${metrics.get('poc_price', 'N/A')}
"""
    
    # Calculate distance to POC if available
    if metrics.get('price') and metrics.get('poc_price'):
        price = float(metrics['price'])
        poc = float(metrics['poc_price'])
        dist_pct = ((price - poc) / poc) * 100
        dist_bps = dist_pct * 100
        report += f"- **Distance to POC:** {dist_pct:+.2f}% ({dist_bps:+.0f} bps)\n"
    
    # Orderflow
    orderflow_imb = metrics.get('orderflow_imbalance') or metrics.get('imb_5s')
    if orderflow_imb is not None:
        report += f"- **Orderflow Imbalance:** {orderflow_imb:+.2f}"
        if abs(orderflow_imb) > 0.5:
            direction = "STRONG BUY" if orderflow_imb > 0 else "STRONG SELL"
            report += f" ⚠️ {direction} PRESSURE"
        report += "\n"
    
    # Spread
    spread_bps = metrics.get('spread_bps')
    if spread_bps is not None:
        report += f"- **Spread:** {spread_bps:.1f} bps\n"
    
    # Volatility
    vol_regime = metrics.get('volatility_regime')
    if vol_regime:
        report += f"- **Volatility Regime:** {vol_regime}\n"
    
    # Trend
    trend_strength = metrics.get('trend_strength')
    if trend_strength is not None:
        report += f"- **Trend Strength:** {trend_strength:.3f}\n"
    
    # Session info (for profile mismatch debugging)
    profile_session = metrics.get('profile_session')
    profile_hour = metrics.get('profile_hour_utc')
    if profile_session or profile_hour is not None:
        report += f"\n### Session Info\n"
        if profile_session:
            report += f"- **Session:** {profile_session}\n"
        if profile_hour is not None:
            report += f"- **Hour UTC:** {profile_hour}\n"
        
        # Check for profile session mismatch
        if trade['profile_id'] and profile_session:
            if 'overnight' in trade['profile_id'].lower() and profile_session != 'overnight':
                report += f"- ⚠️ **PROFILE MISMATCH:** overnight profile selected during {profile_session} session!\n"
    
    # Entry reason
    entry_reason = metrics.get('entry_reason')
    if entry_reason:
        report += f"\n### Entry Logic\n"
        report += f"- **Entry Reason:** {entry_reason}\n"
    
    # Position sizing
    report += f"\n## Position Sizing\n"
    report += f"- **Size:** {entry_context.get('size', 'N/A')}\n"
    report += f"- **Stop Loss:** ${entry_context.get('stop_loss', 'N/A')}\n"
    report += f"- **Take Profit:** ${entry_context.get('take_profit', 'N/A')}\n"
    
    if entry_context.get('entry_price') and entry_context.get('stop_loss'):
        entry_price = float(entry_context['entry_price'])
        stop_loss = float(entry_context['stop_loss'])
        stop_dist_pct = abs((stop_loss - entry_price) / entry_price) * 100
        report += f"- **Stop Distance:** {stop_dist_pct:.2f}%\n"
    
    # Exit analysis
    report += f"\n## Exit Analysis\n"
    report += f"- **Close Reason:** {trade['close_reason'] or 'N/A'}\n"
    report += f"- **Hold Time:** {trade['hold_time_sec']:.0f} seconds\n"
    
    # Fee analysis
    if total_fees and trade['entry_price']:
        fee_bps = (total_fees / (trade['entry_price'] * trade['size'])) * 10000
        report += f"\n## Fee Analysis\n"
        report += f"- **Total Fees:** ${total_fees:.2f} ({fee_bps:.1f} bps)\n"
        
        # Calculate breakeven
        if side == 'long':
            breakeven = trade['entry_price'] * (1 + fee_bps / 10000)
        else:
            breakeven = trade['entry_price'] * (1 - fee_bps / 10000)
        report += f"- **Breakeven Price:** ${breakeven:.2f}\n"
    
    # Issues identified
    report += f"\n## Issues Identified\n\n"
    
    issues_found = False
    
    # Check for profile session mismatch
    if trade['profile_id'] and profile_session:
        if 'overnight' in trade['profile_id'].lower() and profile_session != 'overnight':
            report += f"### 🔴 CRITICAL: Profile Session Mismatch\n"
            report += f"The `{trade['profile_id']}` profile was selected during `{profile_session}` session.\n"
            report += f"This profile requires `overnight` session (22:00-24:00 UTC).\n\n"
            issues_found = True
    
    # Check for adverse orderflow
    if orderflow_imb is not None:
        if (side == 'short' and orderflow_imb > 0.5) or (side == 'long' and orderflow_imb < -0.5):
            report += f"### 🔴 CRITICAL: Adverse Orderflow Entry\n"
            report += f"Entered {side.upper()} with orderflow_imbalance = {orderflow_imb:+.2f}\n"
            report += f"This indicates strong pressure AGAINST our position.\n\n"
            issues_found = True
    
    # Check for premature exit
    if trade['hold_time_sec'] and trade['hold_time_sec'] < 60:
        report += f"### 🟠 HIGH: Premature Exit\n"
        report += f"Position closed after only {trade['hold_time_sec']:.0f} seconds.\n"
        report += f"May not have given the trade enough time to work.\n\n"
        issues_found = True
    
    # Check for small edge after fees
    if trade['entry_price'] and trade['exit_price'] and total_fees is not None:
        if gross_pnl is None:
            gross_pnl = (net_pnl + total_fees) if net_pnl is not None else None
        if gross_pnl is None:
            gross_pnl = trade['realized_pnl'] + total_fees
        gross_pnl_bps = (gross_pnl / (trade['entry_price'] * trade['size'])) * 10000
        if abs(gross_pnl_bps) < 20:  # Less than 20 bps edge
            report += f"### 🟡 MEDIUM: Marginal Edge\n"
            report += f"Gross PnL was only {gross_pnl_bps:.1f} bps before fees.\n"
            report += f"After {fee_bps:.1f} bps in fees, net edge was insufficient.\n\n"
            issues_found = True
    
    if not issues_found:
        report += "No obvious issues identified. This may be a valid losing trade within expected variance.\n\n"
    
    return report


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Trade Forensics Tool')
    parser.add_argument('--limit', type=int, default=10, help='Number of trades to analyze')
    parser.add_argument('--symbol', type=str, help='Filter by symbol')
    parser.add_argument('--output-dir', type=str, default='.kiro/trade-forensics', help='Output directory for reports')
    parser.add_argument('--tenant-id', type=str, help='Tenant ID (defaults to env var)')
    parser.add_argument('--bot-id', type=str, help='Bot ID (defaults to env var)')
    
    args = parser.parse_args()
    
    # Get tenant/bot IDs
    tenant_id = args.tenant_id or _env_value('TENANT_ID') or _env_value('DEFAULT_TENANT_ID', '11111111-1111-1111-1111-111111111111')
    bot_id = args.bot_id or _env_value('BOT_ID') or _env_value('DEFAULT_BOT_ID', 'bot-001')
    
    log_info("trade_forensics_start", tenant_id=tenant_id, bot_id=bot_id, limit=args.limit, symbol=args.symbol)
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Connect to database
    pool = await get_db_pool()
    
    try:
        # Query losing trades
        log_info("querying_losing_trades")
        trades = await query_losing_trades(pool, tenant_id, bot_id, args.symbol, args.limit)
        
        if not trades:
            print("No losing trades found.")
            return
        
        print(f"\nFound {len(trades)} losing trades. Generating forensics reports...\n")
        
        # Generate reports for each trade
        for i, trade in enumerate(trades, 1):
            symbol = trade['symbol']
            side = trade['side']
            timestamp = trade['timestamp']
            
            print(f"[{i}/{len(trades)}] Analyzing {symbol} {side.upper()} @ {timestamp}...")
            
            # Query entry context
            entry_context = await query_entry_context(
                pool,
                tenant_id,
                bot_id,
                symbol,
                side,
                timestamp,
            )
            
            # Generate report
            report = generate_forensics_report(trade, entry_context)
            
            # Save report to file
            ts_str = timestamp.strftime('%Y%m%d_%H%M%S') if isinstance(timestamp, datetime) else str(timestamp).replace(':', '').replace(' ', '_')
            filename = f"{symbol}_{side}_{ts_str}.md"
            filepath = output_dir / filename
            
            with open(filepath, 'w') as f:
                f.write(report)
            
            print(f"  Report saved to: {filepath}")
            
            # Print summary to console
            pnl = trade.get('net_pnl') if trade.get('net_pnl') is not None else trade['realized_pnl']
            pnl_pct = trade['realized_pnl_pct']
            hold_time = trade['hold_time_sec']
            print(f"  PnL: ${pnl:.2f} ({pnl_pct:.2f}%), Hold: {hold_time:.0f}s, Reason: {trade['close_reason']}")
            print()
        
        print(f"\n✅ Generated {len(trades)} forensics reports in {output_dir}")
        
        # Generate summary report
        summary_path = output_dir / "SUMMARY.md"
        with open(summary_path, 'w') as f:
            f.write(f"# Trade Forensics Summary\n\n")
            f.write(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"**Tenant ID:** {tenant_id}\n")
            f.write(f"**Bot ID:** {bot_id}\n")
            f.write(f"**Trades Analyzed:** {len(trades)}\n\n")
            
            f.write(f"## Trades\n\n")
            for trade in trades:
                ts_str = trade['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(trade['timestamp'], datetime) else str(trade['timestamp'])
                f.write(f"- **{trade['symbol']} {trade['side'].upper()}** @ {ts_str}\n")
                pnl = trade.get('net_pnl') if trade.get('net_pnl') is not None else trade['realized_pnl']
                f.write(f"  - PnL: ${pnl:.2f} ({trade['realized_pnl_pct']:.2f}%)\n")
                f.write(f"  - Hold: {trade['hold_time_sec']:.0f}s, Reason: {trade['close_reason']}\n")
                f.write(f"  - Profile: {trade['profile_id']}, Strategy: {trade['strategy_id']}\n\n")
        
        print(f"📊 Summary report saved to: {summary_path}")
        
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
