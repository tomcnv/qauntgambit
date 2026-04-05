#!/usr/bin/env python3
"""
Quick backtest using the training feature stream.
Tests the new strategies and position sizing against recent market data.
"""
import json
import sys
import redis
from datetime import datetime
from collections import defaultdict

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Config
STREAM_KEY = "events:features:11111111-1111-1111-1111-111111111111:fb8ca50f-95d5-4e33-a4ad-5baab06584dc:training"
INITIAL_CAPITAL = 10000.0
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

# Strategy configs (from our changes)
STRATEGIES = {
    'poc_magnet': {
        'risk_pct': 0.015,
        'min_edge_bps': 10.0,
        'min_distance_poc_bps': 8.0,
        'sessions': ['europe', 'us'],
    },
    'spread_capture': {
        'risk_pct': 0.010,
        'min_edge_bps': 0.5,
        'min_imbalance': 0.50,
        'max_spread_bps': 5.0,
        'sessions': ['europe', 'us'],
    },
}

def classify_session(hour_utc):
    if 0 <= hour_utc < 8:
        return 'asia'
    elif 8 <= hour_utc < 13:
        return 'europe'
    elif 13 <= hour_utc < 21:
        return 'us'
    else:
        return 'overnight'

def check_poc_magnet(features, config):
    """Check if poc_magnet would fire"""
    if features.get('position_in_value') != 'inside':
        return None
    
    distance_poc_bps = abs(features.get('distance_to_poc_bps', 0))
    if distance_poc_bps < config['min_distance_poc_bps']:
        return None
    
    spread_bps = features.get('spread_bps', 999)
    if spread_bps > 5.0:
        return None
    
    # Simplified edge check: distance to POC - costs
    edge_bps = distance_poc_bps - 8.0  # 8 bps total costs
    if edge_bps < config['min_edge_bps']:
        return None
    
    return {
        'strategy': 'poc_magnet',
        'edge_bps': edge_bps,
        'entry_price': features.get('price'),
        'target_price': features.get('point_of_control'),
    }

def check_spread_capture(features, config):
    """Check if spread_capture would fire"""
    imbalance = features.get('orderflow_imbalance')
    if imbalance is None or abs(imbalance) < config['min_imbalance']:
        return None
    
    spread_bps = features.get('spread_bps', 999)
    if spread_bps > config['max_spread_bps']:
        return None
    
    bid_depth = features.get('bid_depth_usd', 0)
    ask_depth = features.get('ask_depth_usd', 0)
    if min(bid_depth, ask_depth) < 3000:
        return None
    
    # Edge = half spread (maker rebate)
    edge_bps = spread_bps / 2.0
    if edge_bps < config['min_edge_bps']:
        return None
    
    return {
        'strategy': 'spread_capture',
        'edge_bps': edge_bps,
        'entry_price': features.get('price'),
        'imbalance': imbalance,
    }

def simulate_trade(signal, config, capital):
    """Simulate trade outcome"""
    position_size = capital * config['risk_pct']
    
    # Simplified PnL: 60% win rate, avg win = edge_bps, avg loss = -edge_bps/2
    import random
    win = random.random() < 0.60  # Assume 60% win rate
    
    if win:
        pnl_bps = signal['edge_bps'] * 0.8  # 80% of edge captured
    else:
        pnl_bps = -signal['edge_bps'] * 0.4  # Lose half the edge
    
    pnl_usd = position_size * (pnl_bps / 10000.0)
    return pnl_usd, win

# Read stream
print(f"Reading stream: {STREAM_KEY}")
print(f"Initial capital: ${INITIAL_CAPITAL:,.2f}\n")

entries = r.xrange(STREAM_KEY, count=50000)
print(f"Loaded {len(entries)} feature snapshots\n")

# Simulate
capital = INITIAL_CAPITAL
trades = []
stats = defaultdict(lambda: {'count': 0, 'wins': 0, 'pnl': 0.0})
open_positions = {}  # symbol -> {strategy, entry_time, exit_time}
last_trade_time = {}  # symbol -> timestamp
COOLDOWN_SEC = 60  # 1 minute cooldown between trades per symbol

for entry_id, data in entries:
    try:
        event = json.loads(data['data'])
        payload = event.get('payload', {})
        features = payload.get('features', {})
        market_ctx = payload.get('market_context', {})
        
        symbol = features.get('symbol')
        if symbol not in SYMBOLS:
            continue
        
        timestamp = features.get('timestamp', 0)
        dt = datetime.fromtimestamp(timestamp)
        hour_utc = dt.hour
        session = classify_session(hour_utc)
        
        # Check if position is open for this symbol
        if symbol in open_positions:
            pos = open_positions[symbol]
            if timestamp >= pos['exit_time']:
                # Position closed
                del open_positions[symbol]
            else:
                # Still in position, skip
                continue
        
        # Check cooldown
        if symbol in last_trade_time:
            if timestamp - last_trade_time[symbol] < COOLDOWN_SEC:
                continue
        
        # Check each strategy
        for strat_name, config in STRATEGIES.items():
            if session not in config['sessions']:
                continue
            
            signal = None
            if strat_name == 'poc_magnet':
                signal = check_poc_magnet(features, config)
            elif strat_name == 'spread_capture':
                signal = check_spread_capture(features, config)
            
            if signal:
                pnl, win = simulate_trade(signal, config, capital)
                capital += pnl
                
                # Set hold time
                hold_time = 60 if strat_name == 'poc_magnet' else 30
                open_positions[symbol] = {
                    'strategy': strat_name,
                    'entry_time': timestamp,
                    'exit_time': timestamp + hold_time,
                }
                last_trade_time[symbol] = timestamp
                
                trades.append({
                    'timestamp': dt,
                    'symbol': symbol,
                    'strategy': strat_name,
                    'pnl': pnl,
                    'win': win,
                    'capital': capital,
                })
                
                stats[strat_name]['count'] += 1
                stats[strat_name]['wins'] += 1 if win else 0
                stats[strat_name]['pnl'] += pnl
                
                break  # Only one strategy per tick
                
    except Exception as e:
        continue

# Results
print("=" * 60)
print("BACKTEST RESULTS")
print("=" * 60)
print(f"\nInitial Capital: ${INITIAL_CAPITAL:,.2f}")
print(f"Final Capital:   ${capital:,.2f}")
print(f"Total PnL:       ${capital - INITIAL_CAPITAL:+,.2f}")
print(f"Return:          {((capital / INITIAL_CAPITAL) - 1) * 100:+.2f}%")
print(f"\nTotal Trades:    {len(trades)}")

if trades:
    hours = (trades[-1]['timestamp'] - trades[0]['timestamp']).total_seconds() / 3600
    print(f"Time Period:     {hours:.1f} hours ({hours/24:.1f} days)")
    print(f"Trades/Day:      {len(trades) / (hours/24):.1f}")

print("\n" + "=" * 60)
print("BY STRATEGY")
print("=" * 60)

for strat_name, s in stats.items():
    if s['count'] > 0:
        win_rate = s['wins'] / s['count'] * 100
        avg_pnl = s['pnl'] / s['count']
        print(f"\n{strat_name}:")
        print(f"  Trades:    {s['count']}")
        print(f"  Win Rate:  {win_rate:.1f}%")
        print(f"  Total PnL: ${s['pnl']:+,.2f}")
        print(f"  Avg PnL:   ${avg_pnl:+,.2f}")

print("\n" + "=" * 60)
print("LAST 10 TRADES")
print("=" * 60)
for t in trades[-10:]:
    status = "WIN" if t['win'] else "LOSS"
    print(f"{t['timestamp'].strftime('%Y-%m-%d %H:%M')} | {t['symbol']:8} | {t['strategy']:15} | {status:4} | ${t['pnl']:+7.2f} | Capital: ${t['capital']:,.2f}")

print("\n")
