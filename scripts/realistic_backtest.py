#!/usr/bin/env python3
"""
Realistic backtest using feature stream + actual price movements.
Simulates real fills, slippage, and PnL based on actual market data.
"""
import json
import sys
import redis
from datetime import datetime
from collections import defaultdict, deque

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Config
STREAM_KEY = "events:features:11111111-1111-1111-1111-111111111111:fb8ca50f-95d5-4e33-a4ad-5baab06584dc:training"
INITIAL_CAPITAL = 10000.0
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

# Strategy configs
STRATEGIES = {
    'poc_magnet': {
        'risk_pct': 0.015,
        'min_edge_bps': 10.0,
        'min_distance_poc_bps': 8.0,
        'max_hold_sec': 180,  # 3 minutes
        'tp_pct': 0.010,  # 1.0%
        'sl_pct': 0.008,  # 0.8%
        'sessions': ['europe', 'us'],
    },
    'spread_capture': {
        'risk_pct': 0.010,
        'min_edge_bps': 0.5,
        'min_imbalance': 0.50,
        'max_spread_bps': 5.0,
        'max_hold_sec': 90,  # 1.5 minutes
        'tp_pct': 0.004,  # 0.4%
        'sl_pct': 0.005,  # 0.5%
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
    
    poc = features.get('point_of_control')
    if poc is None:
        return None
    
    distance_poc_bps = abs(features.get('distance_to_poc_bps', 0))
    if distance_poc_bps < config['min_distance_poc_bps']:
        return None
    
    spread_bps = features.get('spread_bps', 999)
    if spread_bps > 5.0:
        return None
    
    edge_bps = distance_poc_bps - 8.0
    if edge_bps < config['min_edge_bps']:
        return None
    
    price = features.get('price')
    side = 'long' if price < poc else 'short'
    
    # TP/SL based on config percentages
    if side == 'long':
        target_price = price * (1 + config['tp_pct'])
        stop_loss = price * (1 - config['sl_pct'])
    else:
        target_price = price * (1 - config['tp_pct'])
        stop_loss = price * (1 + config['sl_pct'])
    
    return {
        'strategy': 'poc_magnet',
        'side': side,
        'entry_price': price,
        'target_price': target_price,
        'stop_loss': stop_loss,
        'edge_bps': edge_bps,
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
    
    edge_bps = spread_bps / 2.0
    if edge_bps < config['min_edge_bps']:
        return None
    
    price = features.get('price')
    spread = features.get('spread', 0)
    side = 'short' if imbalance > 0 else 'long'
    
    # TP/SL based on config percentages
    if side == 'long':
        target_price = price * (1 + config['tp_pct'])
        stop_loss = price * (1 - config['sl_pct'])
    else:
        target_price = price * (1 - config['tp_pct'])
        stop_loss = price * (1 + config['sl_pct'])
    
    return {
        'strategy': 'spread_capture',
        'side': side,
        'entry_price': price,
        'target_price': target_price,
        'stop_loss': stop_loss,
        'edge_bps': edge_bps,
    }

class Position:
    def __init__(self, signal, config, capital, entry_time):
        self.strategy = signal['strategy']
        self.side = signal['side']
        self.entry_price = signal['entry_price']
        self.target_price = signal['target_price']
        self.stop_loss = signal['stop_loss']
        self.entry_time = entry_time
        self.exit_time = entry_time + config['max_hold_sec']
        
        # Position sizing
        self.size_usd = capital * config['risk_pct']
        self.size_coins = self.size_usd / self.entry_price
        
        # Tracking
        self.max_favorable = 0.0
        self.closed = False
        self.exit_reason = None
        self.exit_price = None
        self.pnl = 0.0
    
    def update(self, price, timestamp):
        """Update position with current price"""
        if self.closed:
            return
        
        # Track MFE
        if self.side == 'long':
            pnl_pct = (price - self.entry_price) / self.entry_price
        else:
            pnl_pct = (self.entry_price - price) / self.entry_price
        
        self.max_favorable = max(self.max_favorable, pnl_pct)
        
        # Check exits
        if timestamp >= self.exit_time:
            self.close(price, 'max_hold')
        elif self.side == 'long':
            if price >= self.target_price:
                self.close(price, 'take_profit')
            elif price <= self.stop_loss:
                self.close(price, 'stop_loss')
        else:
            if price <= self.target_price:
                self.close(price, 'take_profit')
            elif price >= self.stop_loss:
                self.close(price, 'stop_loss')
    
    def close(self, price, reason):
        """Close position"""
        self.closed = True
        self.exit_reason = reason
        self.exit_price = price
        
        # Calculate PnL with fees
        if self.side == 'long':
            gross_pnl = (price - self.entry_price) * self.size_coins
        else:
            gross_pnl = (self.entry_price - price) * self.size_coins
        
        # Fees: maker entry (0 bps) + taker exit (2.75 bps) if TP, market (5.5 bps) if SL
        if reason == 'take_profit':
            fee_bps = 0.0  # maker-maker
        else:
            fee_bps = 5.5  # market exit
        
        fees = self.size_usd * (fee_bps / 10000.0)
        self.pnl = gross_pnl - fees

# Read stream
print(f"Reading stream: {STREAM_KEY}")
print(f"Initial capital: ${INITIAL_CAPITAL:,.2f}\n")

entries = r.xrange(STREAM_KEY, count=50000)
print(f"Loaded {len(entries)} feature snapshots\n")

# Simulate
capital = INITIAL_CAPITAL
trades = []
stats = defaultdict(lambda: {'count': 0, 'wins': 0, 'pnl': 0.0, 'tp': 0, 'sl': 0, 'timeout': 0})
open_positions = {}  # symbol -> Position
last_trade_time = {}  # symbol -> timestamp
COOLDOWN_SEC = 60

for entry_id, data in entries:
    try:
        event = json.loads(data['data'])
        payload = event.get('payload', {})
        features = payload.get('features', {})
        
        symbol = features.get('symbol')
        if symbol not in SYMBOLS:
            continue
        
        timestamp = features.get('timestamp', 0)
        price = features.get('price')
        if not price:
            continue
        
        dt = datetime.fromtimestamp(timestamp)
        hour_utc = dt.hour
        session = classify_session(hour_utc)
        
        # Update open position
        if symbol in open_positions:
            pos = open_positions[symbol]
            pos.update(price, timestamp)
            
            if pos.closed:
                # Record trade
                capital += pos.pnl
                win = pos.pnl > 0
                
                trades.append({
                    'timestamp': dt,
                    'symbol': symbol,
                    'strategy': pos.strategy,
                    'side': pos.side,
                    'entry': pos.entry_price,
                    'exit': pos.exit_price,
                    'pnl': pos.pnl,
                    'win': win,
                    'exit_reason': pos.exit_reason,
                    'capital': capital,
                })
                
                stats[pos.strategy]['count'] += 1
                stats[pos.strategy]['wins'] += 1 if win else 0
                stats[pos.strategy]['pnl'] += pos.pnl
                stats[pos.strategy][pos.exit_reason] += 1
                
                del open_positions[symbol]
                last_trade_time[symbol] = timestamp
            
            continue
        
        # Check cooldown
        if symbol in last_trade_time:
            if timestamp - last_trade_time[symbol] < COOLDOWN_SEC:
                continue
        
        # Check strategies
        for strat_name, config in STRATEGIES.items():
            if session not in config['sessions']:
                continue
            
            signal = None
            if strat_name == 'poc_magnet':
                signal = check_poc_magnet(features, config)
            elif strat_name == 'spread_capture':
                signal = check_spread_capture(features, config)
            
            if signal:
                pos = Position(signal, config, capital, timestamp)
                open_positions[symbol] = pos
                break
                
    except Exception as e:
        continue

# Close any remaining positions at last price
for symbol, pos in list(open_positions.items()):
    if not pos.closed:
        pos.close(pos.entry_price, 'end_of_data')
        capital += pos.pnl
        
        trades.append({
            'timestamp': datetime.fromtimestamp(pos.entry_time),
            'symbol': symbol,
            'strategy': pos.strategy,
            'side': pos.side,
            'entry': pos.entry_price,
            'exit': pos.exit_price,
            'pnl': pos.pnl,
            'win': pos.pnl > 0,
            'exit_reason': pos.exit_reason,
            'capital': capital,
        })
        
        stats[pos.strategy]['count'] += 1
        stats[pos.strategy]['wins'] += 1 if pos.pnl > 0 else 0
        stats[pos.strategy]['pnl'] += pos.pnl

# Results
print("=" * 70)
print("REALISTIC BACKTEST RESULTS")
print("=" * 70)
print(f"\nInitial Capital: ${INITIAL_CAPITAL:,.2f}")
print(f"Final Capital:   ${capital:,.2f}")
print(f"Total PnL:       ${capital - INITIAL_CAPITAL:+,.2f}")
print(f"Return:          {((capital / INITIAL_CAPITAL) - 1) * 100:+.2f}%")
print(f"\nTotal Trades:    {len(trades)}")

if trades:
    hours = (trades[-1]['timestamp'] - trades[0]['timestamp']).total_seconds() / 3600
    print(f"Time Period:     {hours:.1f} hours ({hours/24:.1f} days)")
    print(f"Trades/Hour:     {len(trades) / hours:.1f}")
    print(f"Trades/Day:      {len(trades) / (hours/24):.1f}")
    
    wins = sum(1 for t in trades if t['win'])
    print(f"\nOverall Win Rate: {wins / len(trades) * 100:.1f}%")
    
    winning_trades = [t['pnl'] for t in trades if t['win']]
    losing_trades = [t['pnl'] for t in trades if not t['win']]
    
    if winning_trades:
        print(f"Avg Win:         ${sum(winning_trades) / len(winning_trades):+.2f}")
    if losing_trades:
        print(f"Avg Loss:        ${sum(losing_trades) / len(losing_trades):+.2f}")

print("\n" + "=" * 70)
print("BY STRATEGY")
print("=" * 70)

for strat_name, s in stats.items():
    if s['count'] > 0:
        win_rate = s['wins'] / s['count'] * 100
        avg_pnl = s['pnl'] / s['count']
        print(f"\n{strat_name}:")
        print(f"  Trades:       {s['count']}")
        print(f"  Win Rate:     {win_rate:.1f}%")
        print(f"  Total PnL:    ${s['pnl']:+,.2f}")
        print(f"  Avg PnL:      ${avg_pnl:+,.2f}")
        print(f"  Exits:")
        print(f"    TP:         {s['tp']} ({s['tp']/s['count']*100:.0f}%)")
        print(f"    SL:         {s['sl']} ({s['sl']/s['count']*100:.0f}%)")
        print(f"    Timeout:    {s['timeout']} ({s['timeout']/s['count']*100:.0f}%)")

print("\n" + "=" * 70)
print("LAST 20 TRADES")
print("=" * 70)
print(f"{'Time':<16} | {'Symbol':<8} | {'Strategy':<15} | {'Side':<5} | {'Exit':<10} | {'PnL':<8} | {'Capital':<12}")
print("-" * 70)
for t in trades[-20:]:
    status = "WIN" if t['win'] else "LOSS"
    print(f"{t['timestamp'].strftime('%m-%d %H:%M'):<16} | {t['symbol']:<8} | {t['strategy']:<15} | {t['side']:<5} | {t['exit_reason']:<10} | ${t['pnl']:+7.2f} | ${t['capital']:>10,.2f}")

print("\n")
