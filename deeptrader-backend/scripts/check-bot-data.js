/**
 * Check if Python bot has written data to database tables
 */

import pool from '../config/database.js';

async function checkBotData() {
  try {
    console.log('📊 Checking Python bot data in database...\n');

    // Check trades
    const tradesResult = await pool.query(`
      SELECT 
        COUNT(*) as total_trades,
        COUNT(DISTINCT symbol) as symbols,
        COUNT(DISTINCT profile_id) as profiles,
        MIN(exit_time) as first_trade,
        MAX(exit_time) as last_trade,
        SUM(pnl) as total_pnl
      FROM fast_scalper_trades
    `);
    
    const trades = tradesResult.rows[0];
    console.log('📈 Trades Table (fast_scalper_trades):');
    console.log(`   Total trades: ${trades.total_trades}`);
    console.log(`   Symbols: ${trades.symbols}`);
    console.log(`   Profiles: ${trades.profiles}`);
    console.log(`   First trade: ${trades.first_trade || 'None'}`);
    console.log(`   Last trade: ${trades.last_trade || 'None'}`);
    console.log(`   Total PnL: ${parseFloat(trades.total_pnl || 0).toFixed(2)}`);
    console.log('');

    // Check recent trades
    const recentTrades = await pool.query(`
      SELECT symbol, side, size, pnl, exit_time, profile_id
      FROM fast_scalper_trades
      ORDER BY exit_time DESC
      LIMIT 5
    `);
    
    if (recentTrades.rows.length > 0) {
      console.log('📋 Recent Trades (last 5):');
      recentTrades.rows.forEach((trade, i) => {
        console.log(`   ${i + 1}. ${trade.symbol} ${trade.side} ${trade.size} @ ${trade.exit_time} | PnL: ${parseFloat(trade.pnl).toFixed(2)} | Profile: ${trade.profile_id || 'N/A'}`);
      });
      console.log('');
    }

    // Check trades by date
    const tradesByDate = await pool.query(`
      SELECT 
        DATE(exit_time) as date,
        COUNT(*) as trades,
        SUM(pnl) as total_pnl,
        COUNT(DISTINCT symbol) as symbols
      FROM fast_scalper_trades
      GROUP BY DATE(exit_time)
      ORDER BY date DESC
      LIMIT 7
    `);
    
    if (tradesByDate.rows.length > 0) {
      console.log('📅 Trades by Date (last 7 days):');
      tradesByDate.rows.forEach(row => {
        console.log(`   ${row.date}: ${row.trades} trades, ${parseFloat(row.total_pnl).toFixed(2)} PnL, ${row.symbols} symbols`);
      });
      console.log('');
    }

    // Check positions
    const positionsResult = await pool.query(`
      SELECT 
        COUNT(*) FILTER (WHERE status = 'open') as open_positions,
        COUNT(*) FILTER (WHERE status = 'closed') as closed_positions,
        COUNT(DISTINCT symbol) FILTER (WHERE status = 'open') as open_symbols,
        SUM(unrealized_pnl) FILTER (WHERE status = 'open') as total_unrealized_pnl
      FROM fast_scalper_positions
    `);
    
    const positions = positionsResult.rows[0];
    console.log('💼 Positions Table (fast_scalper_positions):');
    console.log(`   Open positions: ${positions.open_positions}`);
    console.log(`   Closed positions: ${positions.closed_positions}`);
    console.log(`   Open symbols: ${positions.open_symbols}`);
    console.log(`   Total unrealized PnL: ${parseFloat(positions.total_unrealized_pnl || 0).toFixed(2)}`);
    console.log('');

    // Check open positions
    const openPositions = await pool.query(`
      SELECT symbol, side, size, entry_price, current_price, unrealized_pnl, profile_id
      FROM fast_scalper_positions
      WHERE status = 'open'
      LIMIT 5
    `);
    
    if (openPositions.rows.length > 0) {
      console.log('📋 Open Positions:');
      openPositions.rows.forEach((pos, i) => {
        console.log(`   ${i + 1}. ${pos.symbol} ${pos.side} ${pos.size} @ ${pos.entry_price} | Current: ${pos.current_price} | PnL: ${parseFloat(pos.unrealized_pnl || 0).toFixed(2)} | Profile: ${pos.profile_id || 'N/A'}`);
      });
      console.log('');
    }

    // Summary
    console.log('✅ Summary:');
    if (parseInt(trades.total_trades) > 0) {
      console.log(`   ✅ Bot has written ${trades.total_trades} trades to database`);
      console.log(`   ✅ Data aggregation should work!`);
    } else {
      console.log(`   ⚠️  No trades found in database`);
      console.log(`   ⚠️  Bot may not be trading yet, or trades not being written`);
    }
    
    if (parseInt(positions.open_positions) > 0) {
      console.log(`   ✅ Bot has ${positions.open_positions} open positions`);
    } else {
      console.log(`   ⚠️  No open positions found`);
    }

  } catch (error) {
    console.error('❌ Error checking bot data:', error);
  } finally {
    await pool.end();
  }
}

checkBotData();




